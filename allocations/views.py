from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import redirect, render

from halls.models import Hall, Room, Seat

from .forms import AssignForm, RevokeForm
from .models import SeatAssignment, SeatAssignmentLog, SeatMaintenance
from .services import assign_seat, revoke_seat


@login_required
def assign(request):
    if request.method == 'POST':
        form = AssignForm(request.POST)
        if form.is_valid():
            try:
                assignment = assign_seat(
                    seat=form.cleaned_data['seat'],
                    student_id=form.cleaned_data['student_id'].strip(),
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
    else:
        form = AssignForm()

    halls = Hall.objects.all()
    context = {
        'page_title': 'Assign Seat',
        'form': form,
        'halls': halls,
    }
    return render(request, 'allocations/assign.html', context)


@login_required
def revoke(request):
    if request.method == 'POST':
        form = RevokeForm(request.POST)
        if form.is_valid():
            try:
                released = revoke_seat(
                    student_id=form.cleaned_data['student_id'].strip(),
                    performed_by=request.user,
                    note='Released from web UI.',
                )
                messages.success(request, f'Released {len(released)} seat assignment(s).')
                return redirect('allocations:active_assignments')
            except ValidationError as e:
                form.add_error('student_id', e)
    else:
        form = RevokeForm()

    context = {
        'page_title': 'Release Seat',
        'form': form,
    }
    return render(request, 'allocations/revoke.html', context)


@login_required
def active_assignments(request):
    assignments = SeatAssignment.objects.filter(is_active=True).select_related(
        'seat__room__floor__block', 'seat__room__floor', 'seat__hall'
    ).order_by('-assigned_at')
    logs = SeatAssignmentLog.objects.select_related('seat__room', 'performed_by')[:20]
    context = {
        'page_title': 'Active Assignments',
        'assignments': assignments,
        'logs': logs,
    }
    return render(request, 'allocations/assignments.html', context)


@login_required
def revoke_assignment(request, pk):
    if request.method == 'POST':
        try:
            assignment = SeatAssignment.objects.get(pk=pk, is_active=True)
            revoke_seat(
                student_id=assignment.student_id,
                seat=assignment.seat,
                performed_by=request.user,
                note='Released from active list.',
            )
            messages.success(request, f'Released {assignment.student_id} from {assignment.seat.seat_label}.')
        except (SeatAssignment.DoesNotExist, ValidationError) as e:
            messages.error(request, str(e) if isinstance(e, ValidationError) else 'Assignment not found.')
    return redirect('allocations:active_assignments')


@login_required
def rooms_json(request):
    hall_id = request.GET.get('hall_id')
    if not hall_id:
        return JsonResponse({'error': 'hall_id required'}, status=400)
    rooms = Room.objects.filter(hall_id=hall_id).select_related('floor').order_by('name')
    data = [{
        'id': room.id,
        'label': f'{room.floor} - {room.name}',
    } for room in rooms]
    return JsonResponse({'rooms': data})


@login_required
def room_seats_json(request):
    room_id = request.GET.get('room_id')
    if not room_id:
        return JsonResponse({'error': 'room_id required'}, status=400)
    seats = Seat.objects.filter(room_id=room_id, is_active=True)
    maintenance_ids = SeatMaintenance.objects.filter(is_active=True).values_list('seat_id', flat=True)

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
