from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from halls.models import Room, Seat
from students.models import Student

from .forms import AssignForm, RevokeForm
from .models import (OrderChoices, SeatAssignment, SeatAssignmentLog, SeatMaintenance,
                     SeatReleaseReason)
from .services import assign_seat, revoke_seat, validate_seat_assignable


def _student_record(student_id):
    """Master-data record from the students table for the confirmation preview."""
    return Student.objects.filter(student_id=student_id).first()


def _seat_snapshot(seat):
    """Hall/seat details plus current occupants, shown before confirming an assign."""
    occupants = list(
        seat.assignments.filter(is_active=True).order_by('order', 'assigned_at'),
    )
    return {
        'seat': seat,
        'occupants': occupants,
        'next_order': OrderChoices.SECONDARY if occupants else OrderChoices.PRIMARY,
        'next_order_display': 'Secondary' if occupants else 'Primary',
    }


def _scoped_assignments(student_id, visible_halls):
    """All active assignments of a student split into managed / elsewhere."""
    active = SeatAssignment.objects.filter(
        student_id=student_id, is_active=True,
    ).select_related('seat__room__floor__block', 'seat__hall').order_by('assigned_at')
    managed_ids = set(visible_halls.values_list('pk', flat=True))
    scoped = [a for a in active if a.seat.hall_id in managed_ids]
    return scoped, active.first()


@login_required
def assign(request):
    visible_halls = request.user.visible_halls()
    preview = None
    if request.method == 'POST':
        action = request.POST.get('action', 'preview')
        form = AssignForm(request.POST, user=request.user)
        if form.is_valid():
            student_id = form.cleaned_data['student_id'].strip()
            seat = form.cleaned_data['seat']
            if action == 'confirm':
                try:
                    assignment = assign_seat(
                        seat=seat,
                        student_id=student_id,
                        performed_by=request.user,
                        note='Assigned from web UI.',
                    )
                    messages.success(
                        request,
                        f'Seat {assignment.seat.seat_label} assigned to {assignment.student_id} '
                        f'as {assignment.get_order_display()}.',
                    )
                    return redirect('allocations:active_assignments')
                except ValidationError as e:
                    form.add_error('seat', e)
            elif action == 'edit':
                # Back to the form from the preview — the bound form re-renders
                # with every previous selection intact; nothing else to do.
                pass
            else:
                # Preview step — run the same conflict checks the real assignment
                # will run, then show student + hall/seat details for confirmation.
                try:
                    validate_seat_assignable(seat, student_id, acting_user=request.user)
                except ValidationError as e:
                    form.add_error('seat', e)
                else:
                    preview = {
                        'student': _student_record(student_id),
                        'snapshot': _seat_snapshot(seat),
                    }
    else:
        form = AssignForm(user=request.user)

    context = {
        'page_title': 'Assign Seat',
        'form': form,
        'halls': visible_halls,
        'single_hall': form.single_hall,
        'preview': preview,
    }
    return render(request, 'allocations/assign.html', context)


@login_required
def revoke(request):
    visible_halls = request.user.visible_halls()
    preview = None
    if request.method == 'POST':
        action = request.POST.get('action', 'preview')
        form = RevokeForm(request.POST)
        if form.is_valid():
            student_id = form.cleaned_data['student_id'].strip()
            if action == 'confirm':
                try:
                    released = revoke_seat(
                        student_id=student_id,
                        performed_by=request.user,
                        note='Released from web UI.',
                        halls=visible_halls,
                        reason=form.cleaned_data['reason'],
                    )
                    messages.success(request, f'Released {len(released)} seat assignment(s).')
                    return redirect('allocations:active_assignments')
                except ValidationError as e:
                    form.add_error('student_id', e)
            elif action == 'edit':
                # Back to the form from the preview — the bound form re-renders
                # with student ID and reason intact; nothing else to do.
                pass
            else:
                # Preview step — resolve what would be released before committing.
                scoped, other = _scoped_assignments(student_id, visible_halls)
                if not scoped:
                    if other:
                        when = timezone.localtime(other.assigned_at).strftime('%d %b %Y, %I:%M %p')
                        form.add_error(
                            'student_id',
                            f'Student {student_id} is assigned to {other.seat.full_label} '
                            f'(allotted {when}). This seat belongs to another hall, so you '
                            f'cannot release it — only the manager of {other.seat.hall.name} can.',
                        )
                    else:
                        form.add_error(
                            'student_id',
                            f'No active seat assignment found for student {student_id}.',
                        )
                else:
                    preview = {
                        'student': _student_record(student_id),
                        'assignments': scoped,
                        'reason': form.cleaned_data['reason'],
                    }
    else:
        form = RevokeForm()

    context = {
        'page_title': 'Release Seat',
        'form': form,
        'preview': preview,
    }
    return render(request, 'allocations/revoke.html', context)


@login_required
def active_assignments(request):
    visible_halls = request.user.visible_halls()
    assignments = SeatAssignment.objects.filter(
        is_active=True, seat__hall__in=visible_halls,
    ).select_related(
        'seat__room__floor__block', 'seat__room__floor', 'seat__hall',
    ).order_by('-assigned_at')
    logs = SeatAssignmentLog.objects.filter(
        seat__hall__in=visible_halls,
    ).select_related('seat__room', 'performed_by', 'release_reason')[:20]
    context = {
        'page_title': 'Active Assignments',
        'assignments': assignments,
        'logs': logs,
        'release_reasons': SeatReleaseReason.objects.filter(is_active=True),
    }
    return render(request, 'allocations/assignments.html', context)


@login_required
def revoke_assignment(request, pk):
    assignment = get_object_or_404(
        SeatAssignment.objects.select_related('seat__room__floor__block', 'seat__hall'),
        pk=pk, is_active=True,
        seat__hall__in=request.user.visible_halls(),
    )
    if request.method == 'POST':
        reason_id = request.POST.get('reason')
        if not reason_id:
            messages.error(request, 'Please select a release reason.')
            return redirect('allocations:revoke_assignment', pk=pk)
        try:
            reason = SeatReleaseReason.objects.get(pk=reason_id, is_active=True)
        except SeatReleaseReason.DoesNotExist:
            messages.error(request, 'Invalid release reason selected.')
            return redirect('allocations:revoke_assignment', pk=pk)
        try:
            revoke_seat(
                student_id=assignment.student_id,
                seat=assignment.seat,
                performed_by=request.user,
                note='Released from active list.',
                reason=reason,
            )
            messages.success(request, f'Released {assignment.student_id} from {assignment.seat.seat_label}.')
        except ValidationError as e:
            messages.error(request, str(e))
            return redirect('allocations:revoke_assignment', pk=pk)
        return redirect('allocations:active_assignments')

    # GET → preview & confirmation page before the release is performed. A reason
    # picked on the Active Assignments list arrives as ?reason=<id> and is shown
    # pre-selected; the dropdown here still lets the user change it.
    initial_reason = None
    raw_reason = request.GET.get('reason')
    if raw_reason:
        try:
            initial_reason = SeatReleaseReason.objects.get(pk=raw_reason, is_active=True)
        except (SeatReleaseReason.DoesNotExist, ValueError, TypeError):
            initial_reason = None
    context = {
        'page_title': 'Confirm Release',
        'assignment': assignment,
        'student': _student_record(assignment.student_id),
        'co_occupants': assignment.seat.assignments.filter(is_active=True).exclude(pk=assignment.pk),
        'reasons': SeatReleaseReason.objects.filter(is_active=True),
        'initial_reason': initial_reason,
    }
    return render(request, 'allocations/revoke_confirm.html', context)


@login_required
def rooms_json(request):
    hall_id = request.GET.get('hall_id')
    if not hall_id:
        return JsonResponse({'error': 'hall_id required'}, status=400)
    rooms = Room.objects.filter(
        hall_id=hall_id, hall__in=request.user.visible_halls(),
    ).select_related('floor__block').order_by('name')
    data = [{
        'id': room.id,
        'label': room.compact_label,
    } for room in rooms]
    return JsonResponse({'rooms': data})


@login_required
def room_seats_json(request):
    room_id = request.GET.get('room_id')
    if not room_id:
        return JsonResponse({'error': 'room_id required'}, status=400)
    visible_halls = request.user.visible_halls()
    seats = Seat.objects.filter(room_id=room_id, is_active=True, hall__in=visible_halls)
    maintenance_ids = SeatMaintenance.objects.filter(
        is_active=True, seat__room_id=room_id, seat__hall__in=visible_halls,
    ).values_list('seat_id', flat=True)

    data = []
    for seat in seats:
        occupants = seat.assignments.filter(is_active=True)
        count = occupants.count()
        if seat.id in maintenance_ids:
            status = 'maintenance'
        elif count >= 2:
            status = 'full'
        elif count == 1:
            status = 'secondary'
        else:
            status = 'free'
        data.append({
            'id': seat.id,
            'label': f'{seat.room.name} / Seat {seat.seat_number}',
            'status': status,
        })
    return JsonResponse({'seats': data})
