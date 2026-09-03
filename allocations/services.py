from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from halls.models import Hall

from .models import (ActionChoices, AllocationCall, HallAllocation,
                     MaintenanceActionChoices, OrderChoices, ResolveRequest,
                     ResolveStatus, SeatAssignment, SeatAssignmentLog,
                     SeatMaintenanceLog)


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


def is_assignment_blocked(assignment):
    """True if assignment has a pending resolve request (row is locked)."""
    return ResolveRequest.objects.filter(assignment=assignment, status=ResolveStatus.PENDING).exists()


def is_seat_blocked(seat, student_id=None):
    """True if seat (or seat+student) has any pending resolve request."""
    qs = ResolveRequest.objects.filter(status=ResolveStatus.PENDING)
    if student_id:
        qs = qs.filter(seat=seat, student_id=student_id)
    else:
        qs = qs.filter(seat=seat)
    return qs.exists()


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
        if is_assignment_blocked(assignment):
            raise ValidationError(
                f'Assignment {assignment.pk} ({assignment.student_id} @ {assignment.seat.seat_label}) is locked — a pending resolve request exists. Wait for admin to resolve or reject it.'
            )
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


# --------------------------------------------------------------------------- #
# Resolve request – snapshot + approve/reject
# --------------------------------------------------------------------------- #

def _fmt_dt(dt):
    """Local Dhaka formatting used in UI: 01 Sep 2026, 10:30 AM. Returns '' on None."""
    if not dt:
        return ''
    try:
        return timezone.localtime(dt).strftime('%d %b %Y, %I:%M %p')
    except Exception:
        try:
            return dt.strftime('%d %b %Y, %I:%M %p')
        except Exception:
            return str(dt)


def build_resolve_snapshot(assignment):
    """Build JSON snapshot for a ResolveRequest before deletion.

    Stores both ISO (machine) and `_display` (human, Dhaka local) for every date
    so the stored snapshot is self-contained and renders nicely without template
    filters (which cannot parse ISO strings). Example: `assigned_at` + `assigned_at_display`.
    """
    from slips.models import Slip
    data = {}
    try:
        data['assignment'] = {
            'id': assignment.pk,
            'student_id': assignment.student_id,
            'seat_id': assignment.seat_id,
            'seat_label': assignment.seat.seat_label if assignment.seat_id else '',
            'full_label': assignment.seat.full_label if assignment.seat_id else '',
            'hall_id': assignment.seat.hall_id if assignment.seat_id else None,
            'hall_name': assignment.seat.hall.name if assignment.seat_id else '',
            'hall_code': getattr(assignment.seat.hall, 'code', '') if assignment.seat_id else '',
            'order': assignment.order,
            'order_display': assignment.get_order_display(),
            'is_active': assignment.is_active,
            'assigned_at': assignment.assigned_at.isoformat() if assignment.assigned_at else None,
            'assigned_at_display': _fmt_dt(assignment.assigned_at),
            'released_at': assignment.released_at.isoformat() if assignment.released_at else None,
            'released_at_display': _fmt_dt(assignment.released_at),
            'released_reason': assignment.released_reason.name if assignment.released_reason_id else None,
        }
    except Exception:
        data['assignment'] = {'id': assignment.pk, 'student_id': assignment.student_id}
    try:
        data['seat'] = {
            'id': assignment.seat_id,
            'seat_label': assignment.seat.seat_label if assignment.seat_id else '',
            'full_label': assignment.seat.full_label if assignment.seat_id else '',
        }
    except Exception:
        data['seat'] = {}
    try:
        data['hall'] = {
            'id': assignment.seat.hall_id if assignment.seat_id else None,
            'name': assignment.seat.hall.name if assignment.seat_id else '',
        }
    except Exception:
        data['hall'] = {}
    try:
        logs = SeatAssignmentLog.objects.filter(seat=assignment.seat, student_id=assignment.student_id).order_by('created_at')
        data['logs'] = [
            {
                'id': l.pk,
                'action': l.action,
                'order': l.order,
                'note': l.note,
                'release_reason': l.release_reason.name if l.release_reason_id else None,
                'performed_by': str(l.performed_by) if l.performed_by_id else None,
                'created_at': l.created_at.isoformat() if l.created_at else None,
                'created_at_display': _fmt_dt(l.created_at),
            } for l in logs
        ]
    except Exception:
        data['logs'] = []
    try:
        slips_qs = Slip.objects.filter(Q(assignment=assignment) | Q(student_id=assignment.student_id, seat=assignment.seat))
        slips_qs = slips_qs.distinct().select_related('hall', 'seat').prefetch_related('items')
        slips_data = []
        for s in slips_qs:
            slips_data.append({
                'id': s.pk,
                'serial_number': s.serial_number,
                'slip_type': s.slip_type,
                'hall_name': s.hall_name_snapshot or (s.hall.name if s.hall_id else ''),
                'seat_label': s.seat_label_snapshot,
                'student_id': s.student_id,
                'student_name': s.student_name,
                'total_amount': str(s.total_amount),
                'total_in_words': s.total_in_words,
                'issued_at': s.issued_at.isoformat() if s.issued_at else None,
                'issued_at_display': _fmt_dt(s.issued_at),
                'event_date': s.event_date.isoformat() if s.event_date else None,
                'event_date_display': _fmt_dt(s.event_date),
                'items': [{'label': i.label, 'amount': str(i.amount)} for i in s.items.all()],
            })
        data['slips'] = slips_data
    except Exception:
        data['slips'] = []
    return data


def approve_resolve_request(resolve_req, admin_user, resolution_note=''):
    """Admin approves – behavior depends on request_type.

    * ASSIGN (mistaken assign): delete the SeatAssignment + ALL associated
      logs/slips (the whole assignment was wrong) -> assignment set to None.
    * RELEASE (mistaken release): ONLY undo the release – reactivate the
      assignment (is_active=True, clear released_at/released_reason) and delete
      ONLY the release logs/slips, keeping the original assign data.
    """
    if resolve_req.status != ResolveStatus.PENDING:
        raise ValidationError('Only pending requests can be resolved.')
    assignment = resolve_req.assignment
    if assignment is None:
        with transaction.atomic():
            resolve_req.status = ResolveStatus.RESOLVED
            resolve_req.resolved_by = admin_user
            resolve_req.resolved_at = timezone.now()
            resolve_req.resolution_note = resolution_note
            snap = dict(resolve_req.snapshot or {})
            snap['resolved_by'] = str(admin_user)
            snap['resolved_at'] = resolve_req.resolved_at.isoformat()
            snap['resolved_at_display'] = _fmt_dt(resolve_req.resolved_at)
            snap['resolution_note'] = resolution_note
            resolve_req.snapshot = snap
            resolve_req.save(update_fields=['status', 'resolved_by', 'resolved_at', 'resolution_note', 'snapshot'])
        return resolve_req

    fresh_snapshot = build_resolve_snapshot(assignment)
    merged = dict(resolve_req.snapshot or {})
    merged.update(fresh_snapshot)
    now = timezone.now()
    merged['resolved_by'] = str(admin_user)
    merged['resolved_at'] = now.isoformat()
    merged['resolved_at_display'] = _fmt_dt(now)
    merged['resolution_note'] = resolution_note
    merged['requested_by'] = str(resolve_req.requested_by) if resolve_req.requested_by_id else merged.get('requested_by')
    merged['request_type'] = resolve_req.request_type

    # Determine type – default to ASSIGN if missing (backward compat)
    from allocations.models import ResolveType
    is_release_resolve = resolve_req.request_type == ResolveType.RELEASE

    with transaction.atomic():
        req_locked = ResolveRequest.objects.select_for_update().get(pk=resolve_req.pk)
        if req_locked.status != ResolveStatus.PENDING:
            raise ValidationError('Request is no longer pending.')
        from slips.models import Slip, SlipType

        if is_release_resolve:
            # --- RELEASE resolve: only undo the release ---
            # Delete ONLY release slips
            release_slips = Slip.objects.filter(
                Q(assignment=assignment) | Q(student_id=assignment.student_id, seat=assignment.seat),
                slip_type=SlipType.RELEASE
            ).distinct()
            release_slip_ids = list(release_slips.values_list('pk', flat=True))
            merged['deleted_slip_ids'] = release_slip_ids
            merged['deleted_release_slip_ids'] = release_slip_ids
            release_slips.delete()

            # Delete ONLY release logs
            release_logs = SeatAssignmentLog.objects.filter(
                seat=assignment.seat, student_id=assignment.student_id, action=ActionChoices.RELEASED
            )
            release_log_ids = list(release_logs.values_list('pk', flat=True))
            merged['deleted_release_log_ids'] = release_log_ids
            release_logs.delete()

            # Reactivate the assignment (undo release)
            # Use queryset update to bypass full_clean/ValidationError edge cases
            SeatAssignment.objects.filter(pk=assignment.pk).update(
                is_active=True, released_at=None, released_reason=None
            )
            merged['action_taken'] = 'release_revoked_assignment_reactivated'

            req_locked.status = ResolveStatus.RESOLVED
            req_locked.resolved_by = admin_user
            req_locked.resolved_at = timezone.now()
            req_locked.resolution_note = resolution_note
            req_locked.snapshot = merged
            # Keep assignment FK (still valid) – do NOT null it
            req_locked.save(update_fields=['status', 'resolved_by', 'resolved_at', 'resolution_note', 'snapshot'])
        else:
            # --- ASSIGN resolve: delete whole assignment + all slips/logs ---
            slips_to_delete = Slip.objects.filter(Q(assignment=assignment) | Q(student_id=assignment.student_id, seat=assignment.seat)).distinct()
            slip_ids = list(slips_to_delete.values_list('pk', flat=True))
            merged['deleted_slip_ids'] = slip_ids
            slips_to_delete.delete()
            SeatAssignmentLog.objects.filter(seat=assignment.seat, student_id=assignment.student_id).delete()
            SeatAssignment.objects.filter(pk=assignment.pk).delete()
            merged['action_taken'] = 'assignment_and_all_slips_deleted'
            req_locked.status = ResolveStatus.RESOLVED
            req_locked.resolved_by = admin_user
            req_locked.resolved_at = timezone.now()
            req_locked.resolution_note = resolution_note
            req_locked.snapshot = merged
            req_locked.assignment = None  # ensure null after delete
            req_locked.save(update_fields=['status', 'resolved_by', 'resolved_at', 'resolution_note', 'snapshot', 'assignment'])
    return ResolveRequest.objects.get(pk=resolve_req.pk)


def reject_resolve_request(resolve_req, admin_user, resolution_note=''):
    """Admin rejects – keep assignment, just mark rejected (unblock)."""
    if resolve_req.status != ResolveStatus.PENDING:
        raise ValidationError('Only pending requests can be rejected.')
    with transaction.atomic():
        req_locked = ResolveRequest.objects.select_for_update().get(pk=resolve_req.pk)
        if req_locked.status != ResolveStatus.PENDING:
            raise ValidationError('Request is no longer pending.')
        now = timezone.now()
        snap = dict(req_locked.snapshot or {})
        snap['resolved_by'] = str(admin_user)
        snap['resolved_at'] = now.isoformat()
        snap['resolved_at_display'] = _fmt_dt(now)
        snap['resolution_note'] = resolution_note
        req_locked.status = ResolveStatus.REJECTED
        req_locked.resolved_by = admin_user
        req_locked.resolved_at = now
        req_locked.resolution_note = resolution_note
        req_locked.snapshot = snap
        req_locked.save(update_fields=['status', 'resolved_by', 'resolved_at', 'resolution_note', 'snapshot'])
    return req_locked
