from django.core.exceptions import ValidationError
from django.utils import timezone

from halls.models import Hall

from .models import (ActionChoices, AllocationCall, HallAllocation, OrderChoices,
                     SeatAssignment, SeatAssignmentLog)


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
            acting_user.is_superuser
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
            f'Student {student_id} was allotted {allotted_name} (merit position '
            f'{allotment.merit_pos}, call {active_call.call_id}) — not {this_hall}. '
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


def put_seat_under_maintenance(seat, reason, note=''):
    """Move a seat into maintenance (releasing any active assignments)."""
    if seat.assignments.filter(is_active=True).exists():
        raise ValidationError('This seat has active student(s). Release them before putting it on hold.')
    from .models import SeatMaintenance
    record = SeatMaintenance(seat=seat, reason=reason, note=note, is_active=True)
    record.full_clean()
    record.save()
    return record
