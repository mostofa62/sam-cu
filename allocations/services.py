from django.core.exceptions import ValidationError
from django.utils import timezone

from halls.models import Hall

from .models import (ActionChoices, AllocationCall, HallAllocation,
                     MaintenanceActionChoices, OrderChoices, SeatAssignment,
                     SeatAssignmentLog, SeatMaintenanceLog)


def _already_assigned_message(assignment, acting_user=None):
    """Message for a student who already holds an active seat elsewhere.

    The ''release'' advice only appears when the acting user is allowed to release
    that seat (superuser, or manager of the seat's own hall). Otherwise we just
    state the facts and point to that hall's manager.
    """
    when = timezone.localtime(assignment.assigned_at).strftime('%d %b %Y, %I:%M %p')
    message = (
        f'Student {assignment.student_id} already has an active seat assigned — '
        f'{assignment.seat.full_label} (allotted {when}).'
    )
    can_release = (
        acting_user is not None
        and (
            acting_user.is_app_admin
            or acting_user.visible_halls().filter(pk=assignment.seat.hall_id).exists()
        )
    )
    if can_release:
        message += ' Release it from the Active Assignments page.'
    elif acting_user is not None:
        message += (
            f' The seat belongs to another hall — contact the manager of '
            f'{assignment.seat.hall.name} to release it.'
        )
    return message


def _validate_allotment(seat, student_id):
    """Merit-list gate: the student must be allotted this seat's hall in the active call.

    Skipped entirely when no call has been imported yet (nothing to validate
    against), so the system still works before the first import.
    """
    active_call = AllocationCall.active()
    if active_call is None:
        return None

    try:
        allotment = HallAllocation.objects.select_related('call').get(
            call=active_call, student_id=student_id,
        )
    except HallAllocation.DoesNotExist:
        raise ValidationError(
            f'Student {student_id} has no hall allotment in the active allocation call '
            f'{active_call.call_id} — only students allotted by the merit list can be assigned.'
        ) from None

    seat_code = seat.hall.code
    if seat_code and allotment.hall_code != seat_code:
        allotted_hall = Hall.objects.filter(code=allotment.hall_code).first()
        allotted_name = f'{allotted_hall.name} ({allotment.hall_code})' if allotted_hall else allotment.hall_code
        this_hall = f'{seat.hall.name} ({seat_code})'
        raise ValidationError(
            f'Student {student_id} was allotted {allotted_name} (call {active_call.call_id}) — not {this_hall}. '
            f'The allotted hall must match before a seat can be assigned here.'
        )
    return allotment


def validate_seat_assignable(seat, student_id, acting_user=None):
    """Raise ValidationError when ``student_id`` cannot currently take ``seat``.

    Pure check — mutates nothing. Shared by the confirmation preview (to surface
    conflicts before the user commits) and by ``assign_seat`` right before it
    writes, so a seat that filled up between preview and confirm is still caught.
    Returns the matching merit-list allotment when an active call gates the
    assignment (None otherwise).
    """
    allotment = _validate_allotment(seat, student_id)

    active_assignments = seat.assignments.filter(is_active=True)

    if active_assignments.filter(student_id=student_id).exists():
        raise ValidationError(f'Student {student_id} already has this seat assigned.')

    other = SeatAssignment.objects.filter(
        student_id=student_id, is_active=True,
    ).exclude(seat=seat).select_related(
        'seat__room__floor__block', 'seat__hall',
    ).first()
    if other:
        raise ValidationError(_already_assigned_message(other, acting_user=acting_user))

    if seat.under_maintenance:
        raise ValidationError('This seat is on hold and cannot be assigned.')

    if active_assignments.count() >= 2:
        raise ValidationError('This seat already has two active students. Release one first.')

    return allotment


def assign_seat(seat, student_id, performed_by=None, note=''):
    """Assign a seat to a student. Auto-picks primary/secondary order based on current occupants."""
    validate_seat_assignable(seat, student_id, acting_user=performed_by)
    active_assignments = seat.assignments.filter(is_active=True)
    order = OrderChoices.SECONDARY if active_assignments.exists() else OrderChoices.PRIMARY

    assignment = SeatAssignment(
        seat=seat,
        student_id=student_id,
        order=order,
        is_active=True,
    )
    try:
        assignment.full_clean()
        assignment.save()
    except ValidationError as exc:
        raise ValidationError(exc.messages[0]) from exc

    SeatAssignmentLog.objects.create(
        student_id=student_id,
        seat=seat,
        order=order,
        action=ActionChoices.ASSIGNED,
        note=note,
        performed_by=performed_by,
    )
    return assignment


def revoke_seat(student_id, seat=None, performed_by=None, note='', halls=None, reason=None):
    """Release all active seat assignment(s) of a student, optionally for a specific seat.

    Pass ``halls`` (an iterable/queryset of Hall) to limit the release to assignments
    inside those halls — used to stop a hall manager from releasing seats in halls
    they do not manage. ``reason`` must be a ``SeatReleaseReason`` — it is required
    and recorded on the assignment and in the activity log.
    """
    if reason is None:
        raise ValidationError('A release reason must be selected.')

    assignments = SeatAssignment.objects.filter(student_id=student_id, is_active=True)
    if seat is not None:
        assignments = assignments.filter(seat=seat)
    if halls is not None:
        assignments = assignments.filter(seat__hall__in=halls)

    if not assignments.exists():
        # The student may hold an active seat outside the caller's scope — say
        # where it is instead of a misleading "not found" message, so the manager
        # does not try to release something they do not own.
        other = SeatAssignment.objects.filter(
            student_id=student_id, is_active=True,
        ).select_related('seat__room__floor__block', 'seat__hall').first()
        if other:
            when = timezone.localtime(other.assigned_at).strftime('%d %b %Y, %I:%M %p')
            raise ValidationError(
                f'Student {student_id} is assigned to {other.seat.full_label} '
                f'(allotted {when}). This seat belongs to another hall, so you '
                f'cannot release it — only the manager of {other.seat.hall.name} can.'
            )
        raise ValidationError(f'No active seat assignment found for student {student_id}.')

    released = []
    for assignment in assignments:
        assignment.is_active = False
        assignment.released_reason = reason
        assignment.save(update_fields=['is_active', 'released_at', 'released_reason'])
        SeatAssignmentLog.objects.create(
            student_id=student_id,
            seat=assignment.seat,
            order=assignment.order,
            action=ActionChoices.RELEASED,
            note=note,
            release_reason=reason,
            performed_by=performed_by,
        )
        released.append(assignment)
    return released


def put_seat_under_maintenance(seat, reason, note='', performed_by=None, started_at=None, ended_at=None):
    """Move a seat into maintenance for a time window. Logs who did it.

    ``reason`` may be a ``SeatMaintenanceReason`` instance or a plain string.
    """
    if seat.assignments.filter(is_active=True).exists():
        raise ValidationError('This seat has active student(s). Release them before putting it on hold.')
    if seat.maintenance_records.filter(is_active=True).exists():
        raise ValidationError('This seat is already on hold.')
    if performed_by is not None and not performed_by.is_app_admin:
        if not performed_by.visible_halls().filter(pk=seat.hall_id).exists():
            raise ValidationError('You do not have access to this hall.')
    if not started_at or not ended_at:
        raise ValidationError('Both start and end time are required.')
    if ended_at <= started_at:
        raise ValidationError('End time must be after start time.')
    from .models import SeatMaintenance, SeatMaintenanceReason
    # Normalize reason to both string and FK
    maintenance_reason_obj = None
    reason_str = reason
    if isinstance(reason, SeatMaintenanceReason):
        maintenance_reason_obj = reason
        reason_str = reason.name
    elif reason is not None:
        reason_str = str(reason).strip()
        # try to resolve to FK if an active reason with that name exists
        try:
            maintenance_reason_obj = SeatMaintenanceReason.objects.get(name=reason_str)
        except SeatMaintenanceReason.DoesNotExist:
            maintenance_reason_obj = None
    if not reason_str:
        raise ValidationError('A maintenance reason must be selected.')
    kwargs = dict(seat=seat, reason=reason_str, maintenance_reason=maintenance_reason_obj,
                  note=note, is_active=True, started_by=performed_by)
    kwargs['started_at'] = started_at
    kwargs['ended_at'] = ended_at
    record = SeatMaintenance(**kwargs)
    record.full_clean()
    record.save()
    log_note = note
    SeatMaintenanceLog.objects.create(
        seat=seat,
        maintenance=record,
        action=MaintenanceActionChoices.PUT_ON,
        reason=reason_str,
        note=log_note,
        performed_by=performed_by,
    )
    return record


def remove_seat_from_maintenance(seat, performed_by=None, note=''):
    """Remove a seat from maintenance. Logs who removed it."""
    from .models import SeatMaintenance
    record = seat.maintenance_records.filter(is_active=True).first()
    if record is None:
        raise ValidationError('This seat is not on hold.')
    if performed_by is not None and not performed_by.is_app_admin:
        if not performed_by.visible_halls().filter(pk=seat.hall_id).exists():
            raise ValidationError('You do not have access to this hall.')
    record.is_active = False
    record.ended_by = performed_by
    # ended_at auto-set in model save when is_active=False
    record.save(update_fields=['is_active', 'ended_at', 'ended_by'])
    SeatMaintenanceLog.objects.create(
        seat=seat,
        maintenance=record,
        action=MaintenanceActionChoices.REMOVED,
        reason=record.reason,
        note=note,
        performed_by=performed_by,
    )
    return record
