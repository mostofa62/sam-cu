from django.core.exceptions import ValidationError

from .models import ActionChoices, OrderChoices, SeatAssignment, SeatAssignmentLog


def assign_seat(seat, student_id, performed_by=None, note=''):
    """Assign a seat to a student. Auto-picks primary/secondary order based on current occupants."""
    active_assignments = seat.assignments.filter(is_active=True)

    if active_assignments.exists() and active_assignments.filter(student_id=student_id).exists():
        raise ValidationError(f'Student {student_id} already has this seat assigned.')

    if seat.under_maintenance:
        raise ValidationError('This seat is on hold and cannot be assigned.')

    if active_assignments.filter(student_id=student_id).exists():
        raise ValidationError(f'Student {student_id} is already assigned to this seat.')

    if active_assignments.count() >= 2:
        raise ValidationError('This seat already has two active students. Release one first.')

    order = OrderChoices.SECONDARY if active_assignments.exists() else OrderChoices.PRIMARY

    assignment = SeatAssignment(
        seat=seat,
        student_id=student_id,
        order=order,
        is_active=True,
    )
    assignment.full_clean()
    assignment.save()

    SeatAssignmentLog.objects.create(
        student_id=student_id,
        seat=seat,
        order=order,
        action=ActionChoices.ASSIGNED,
        note=note,
        performed_by=performed_by,
    )
    return assignment


def revoke_seat(student_id, seat=None, performed_by=None, note=''):
    """Release all active seat assignment(s) of a student, optionally for a specific seat."""
    assignments = SeatAssignment.objects.filter(student_id=student_id, is_active=True)
    if seat is not None:
        assignments = assignments.filter(seat=seat)

    if not assignments.exists():
        raise ValidationError(f'No active seat assignment found for student {student_id}.')

    released = []
    for assignment in assignments:
        assignment.is_active = False
        assignment.save(update_fields=['is_active', 'released_at'])
        SeatAssignmentLog.objects.create(
            student_id=student_id,
            seat=assignment.seat,
            order=assignment.order,
            action=ActionChoices.RELEASED,
            note=note,
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
