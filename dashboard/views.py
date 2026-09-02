from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import render

from allocations.models import SeatAssignment, SeatAssignmentLog, SeatMaintenance
from halls.models import Block, Floor, Room, Seat


@login_required
def home(request):
    visible_halls = request.user.visible_halls()
    assigned_ids = SeatAssignment.objects.filter(
        is_active=True, seat__hall__in=visible_halls,
    ).values_list('seat_id', flat=True)

    total_halls = visible_halls.exclude(code__isnull=True).exclude(code='').values('code').distinct().count()
    total_blocks = Block.objects.filter(hall__in=visible_halls).count()
    total_floors = Floor.objects.filter(hall__in=visible_halls).count()
    total_rooms = Room.objects.filter(hall__in=visible_halls).count()
    total_seats = Seat.objects.filter(hall__in=visible_halls).count()
    free_seats = total_seats - len(set(assigned_ids))
    occupied_seats = len(set(assigned_ids))
    under_maintenance = SeatMaintenance.objects.filter(is_active=True, seat__hall__in=visible_halls).count()

    halls = visible_halls.annotate(
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

    recent_assignments = SeatAssignment.objects.filter(
        is_active=True, seat__hall__in=visible_halls,
    ).select_related('seat__room').order_by('-assigned_at')[:10]
    recent_logs = SeatAssignmentLog.objects.filter(
        seat__hall__in=visible_halls,
    ).select_related('seat__room').order_by('-created_at')[:8]
    active_maintenance = SeatMaintenance.objects.filter(
        is_active=True, seat__hall__in=visible_halls,
    ).select_related('seat__room')[:6]

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
