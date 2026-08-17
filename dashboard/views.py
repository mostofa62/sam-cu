from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import render

from allocations.models import SeatAssignment, SeatAssignmentLog, SeatMaintenance
from halls.models import Block, Floor, Hall, Room, Seat


@login_required
def home(request):
    assigned_ids = SeatAssignment.objects.filter(is_active=True).values_list('seat_id', flat=True)

    total_halls = Hall.objects.count()
    total_blocks = Block.objects.count()
    total_floors = Floor.objects.count()
    total_rooms = Room.objects.count()
    total_seats = Seat.objects.count()
    free_seats = total_seats - len(set(assigned_ids))
    occupied_seats = len(set(assigned_ids))
    under_maintenance = SeatMaintenance.objects.filter(is_active=True).count()

    halls = Hall.objects.annotate(
        seat_count=Count('seats', distinct=True),
        room_count=Count('rooms', distinct=True),
    )
    hall_stats = []
    for hall in halls:
        free = hall.free_seats
        occupied = hall.seat_count - free
        percentage = round((free / hall.seat_count * 100) if hall.seat_count else 0, 1)
        hall_stats.append({
            'hall': hall,
            'free': free,
            'occupied': occupied,
            'percentage': percentage,
        })

    recent_assignments = SeatAssignment.objects.filter(is_active=True).select_related('seat__room').order_by(
        '-assigned_at')[:10]
    recent_logs = SeatAssignmentLog.objects.select_related('seat__room').order_by('-created_at')[:8]
    active_maintenance = SeatMaintenance.objects.filter(is_active=True).select_related('seat__room')[:6]

    context = {
        'page_title': 'Dashboard',
        'total_halls': total_halls,
        'total_blocks': total_blocks,
        'total_floors': total_floors,
        'total_rooms': total_rooms,
        'total_seats': total_seats,
        'free_seats': free_seats,
        'occupied_seats': occupied_seats,
        'under_maintenance': under_maintenance,
        'hall_stats': hall_stats,
        'recent_assignments': recent_assignments,
        'recent_logs': recent_logs,
        'active_maintenance': active_maintenance,
    }
    return render(request, 'dashboard/home.html', context)
