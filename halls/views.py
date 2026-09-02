from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from adminpanel.pagination import CursorPaginator

from .forms import ManagerBlockForm, ManagerFloorForm, ManagerRoomForm, ManagerSeatForm
from .models import Block, Floor, Room, Seat

PAGE_SIZE = 25

def _visible_halls(request):
    halls = request.user.visible_halls()
    if not halls.exists():
        messages.error(request, 'You have no hall assignment — contact admin.')
    return halls

def _check_owner(obj, user):
    if not obj.is_editable_by(user):
        raise PermissionDenied('You can only edit/delete your own records.')

def _block_in_use(block):
    from allocations.models import SeatAssignment, SeatMaintenance
    from slips.models import Slip
    return (
        SeatAssignment.objects.filter(seat__room__floor__block=block).exists()
        or SeatMaintenance.objects.filter(seat__room__floor__block=block).exists()
        or Slip.objects.filter(seat__room__floor__block=block).exists()
    )

def _floor_in_use(floor):
    from allocations.models import SeatAssignment, SeatMaintenance
    from slips.models import Slip
    return (
        SeatAssignment.objects.filter(seat__room__floor=floor).exists()
        or SeatMaintenance.objects.filter(seat__room__floor=floor).exists()
        or Slip.objects.filter(seat__room__floor=floor).exists()
    )

def _room_in_use(room):
    from allocations.models import SeatAssignment, SeatMaintenance
    from slips.models import Slip
    return (
        SeatAssignment.objects.filter(seat__room=room).exists()
        or SeatMaintenance.objects.filter(seat__room=room).exists()
        or Slip.objects.filter(seat__room=room).exists()
    )

def _seat_in_use(seat):
    from allocations.models import SeatAssignment, SeatMaintenance, SeatAssignmentLog, SeatMaintenanceLog
    from slips.models import Slip
    return (
        SeatAssignment.objects.filter(seat=seat).exists()
        or SeatMaintenance.objects.filter(seat=seat).exists()
        or SeatAssignmentLog.objects.filter(seat=seat).exists()
        or SeatMaintenanceLog.objects.filter(seat=seat).exists()
        or Slip.objects.filter(seat=seat).exists()
    )

# ---------------- Block ----------------
@login_required
def block_list(request):
    halls = _visible_halls(request)
    q = (request.GET.get('q') or '').strip()
    qs = Block.objects.filter(hall__in=halls).select_related('hall', 'created_by')
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(hall__name__icontains=q))
    paginator = CursorPaginator(qs, page_size=PAGE_SIZE, order_field='pk', reverse=True)
    page = paginator.page(request.GET.get('cursor'))
    params = request.GET.copy()
    params.pop('cursor', None)
    qs_str = params.urlencode()
    querystring = f'{qs_str}&' if qs_str else ''
    return render(request, 'halls/block_list.html', {'page_obj': page, 'objects': page.object_list, 'querystring': querystring, 'q': q, 'page_title': 'My Blocks'})

@login_required
def block_add(request):
    halls = _visible_halls(request)
    if request.method == 'POST':
        form = ManagerBlockForm(request.POST, user=request.user)
        if form.is_valid():
            obj = form.save(commit=False)
            if obj.hall_id not in halls.values_list('pk', flat=True):
                messages.error(request, 'Invalid hall.')
                return redirect('halls:block_list')
            obj.created_by = request.user
            obj.save()
            messages.success(request, f'Block "{obj.name}" created.')
            return redirect('halls:block_list')
    else:
        form = ManagerBlockForm(user=request.user)
    return render(request, 'halls/object_form.html', {'form': form, 'page_title': 'Add Block', 'heading': 'New Block'})

@login_required
def block_edit(request, pk):
    halls = _visible_halls(request)
    obj = get_object_or_404(Block, pk=pk, hall__in=halls)
    _check_owner(obj, request.user)
    if _block_in_use(obj):
        messages.error(request, f'Cannot edit block "{obj.name}" — it is in use (has assignments/slips). Editing is blocked to keep slips/assignments consistent.')
        return redirect('halls:block_list')
    if request.method == 'POST':
        form = ManagerBlockForm(request.POST, instance=obj, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, f'Block "{obj.name}" updated.')
            return redirect('halls:block_list')
    else:
        form = ManagerBlockForm(instance=obj, user=request.user)
    return render(request, 'halls/object_form.html', {'form': form, 'page_title': 'Edit Block', 'heading': f'Edit {obj.name}'})

@login_required
def block_delete(request, pk):
    halls = _visible_halls(request)
    obj = get_object_or_404(Block, pk=pk, hall__in=halls)
    _check_owner(obj, request.user)
    has_floors = Floor.objects.filter(block=obj).exists()
    if has_floors and request.method == 'POST':
        messages.error(request, f'Cannot delete block "{obj.name}" — it still has floors. Move or delete floors first.')
        return redirect('halls:block_list')
    if request.method == 'POST':
        name = obj.name
        obj.delete()
        messages.success(request, f'Block "{name}" deleted.')
        return redirect('halls:block_list')
    return render(request, 'halls/object_confirm_delete.html', {'object': obj, 'page_title': 'Delete Block', 'has_data': has_floors})

# ---------------- Floor ----------------
@login_required
def floor_list(request):
    halls = _visible_halls(request)
    q = (request.GET.get('q') or '').strip()
    qs = Floor.objects.filter(hall__in=halls).select_related('hall', 'block', 'created_by')
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(hall__name__icontains=q) | Q(block__name__icontains=q))
    paginator = CursorPaginator(qs, page_size=PAGE_SIZE, order_field='pk', reverse=True)
    page = paginator.page(request.GET.get('cursor'))
    params = request.GET.copy()
    params.pop('cursor', None)
    qs_str = params.urlencode()
    querystring = f'{qs_str}&' if qs_str else ''
    return render(request, 'halls/floor_list.html', {'page_obj': page, 'objects': page.object_list, 'querystring': querystring, 'q': q, 'page_title': 'My Floors'})

@login_required
def floor_add(request):
    halls = _visible_halls(request)
    if request.method == 'POST':
        form = ManagerFloorForm(request.POST, user=request.user)
        if form.is_valid():
            obj = form.save(commit=False)
            if obj.hall_id not in halls.values_list('pk', flat=True):
                messages.error(request, 'Invalid hall.')
                return redirect('halls:floor_list')
            obj.created_by = request.user
            obj.save()
            messages.success(request, f'Floor "{obj.name}" created.')
            return redirect('halls:floor_list')
    else:
        form = ManagerFloorForm(user=request.user)
    return render(request, 'halls/object_form.html', {'form': form, 'page_title': 'Add Floor', 'heading': 'New Floor'})

@login_required
def floor_edit(request, pk):
    halls = _visible_halls(request)
    obj = get_object_or_404(Floor, pk=pk, hall__in=halls)
    _check_owner(obj, request.user)
    if _floor_in_use(obj):
        messages.error(request, f'Cannot edit floor "{obj.name}" — it is in use (has assignments/slips).')
        return redirect('halls:floor_list')
    if request.method == 'POST':
        form = ManagerFloorForm(request.POST, instance=obj, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, f'Floor "{obj.name}" updated.')
            return redirect('halls:floor_list')
    else:
        form = ManagerFloorForm(instance=obj, user=request.user)
    return render(request, 'halls/object_form.html', {'form': form, 'page_title': 'Edit Floor', 'heading': f'Edit {obj.name}'})

@login_required
def floor_delete(request, pk):
    halls = _visible_halls(request)
    obj = get_object_or_404(Floor, pk=pk, hall__in=halls)
    _check_owner(obj, request.user)
    has_rooms = Room.objects.filter(floor=obj).exists()
    if has_rooms and request.method == 'POST':
        messages.error(request, f'Cannot delete floor "{obj.name}" — it still has rooms.')
        return redirect('halls:floor_list')
    if request.method == 'POST':
        name = obj.name
        obj.delete()
        messages.success(request, f'Floor "{name}" deleted.')
        return redirect('halls:floor_list')
    return render(request, 'halls/object_confirm_delete.html', {'object': obj, 'page_title': 'Delete Floor', 'has_data': has_rooms})

# ---------------- Room ----------------
@login_required
def room_list(request):
    halls = _visible_halls(request)
    q = (request.GET.get('q') or '').strip()
    qs = Room.objects.filter(hall__in=halls).select_related('hall', 'floor', 'floor__block', 'created_by')
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(hall__name__icontains=q) | Q(floor__name__icontains=q))
    paginator = CursorPaginator(qs, page_size=PAGE_SIZE, order_field='pk', reverse=True)
    page = paginator.page(request.GET.get('cursor'))
    params = request.GET.copy()
    params.pop('cursor', None)
    qs_str = params.urlencode()
    querystring = f'{qs_str}&' if qs_str else ''
    return render(request, 'halls/room_list.html', {'page_obj': page, 'objects': page.object_list, 'querystring': querystring, 'q': q, 'page_title': 'My Rooms'})

@login_required
def room_add(request):
    halls = _visible_halls(request)
    if request.method == 'POST':
        form = ManagerRoomForm(request.POST, user=request.user)
        if form.is_valid():
            obj = form.save(commit=False)
            if obj.hall_id not in halls.values_list('pk', flat=True):
                messages.error(request, 'Invalid hall.')
                return redirect('halls:room_list')
            obj.created_by = request.user
            obj.save()
            messages.success(request, f'Room "{obj.name}" created.')
            return redirect('halls:room_list')
    else:
        form = ManagerRoomForm(user=request.user)
    return render(request, 'halls/object_form.html', {'form': form, 'page_title': 'Add Room', 'heading': 'New Room'})

@login_required
def room_edit(request, pk):
    halls = _visible_halls(request)
    obj = get_object_or_404(Room, pk=pk, hall__in=halls)
    _check_owner(obj, request.user)
    if _room_in_use(obj):
        messages.error(request, f'Cannot edit room "{obj.name}" — it is in use (has seat assignments/slips).')
        return redirect('halls:room_list')
    if request.method == 'POST':
        form = ManagerRoomForm(request.POST, instance=obj, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, f'Room "{obj.name}" updated.')
            return redirect('halls:room_list')
    else:
        form = ManagerRoomForm(instance=obj, user=request.user)
    return render(request, 'halls/object_form.html', {'form': form, 'page_title': 'Edit Room', 'heading': f'Edit {obj.name}'})

@login_required
def room_delete(request, pk):
    halls = _visible_halls(request)
    obj = get_object_or_404(Room, pk=pk, hall__in=halls)
    _check_owner(obj, request.user)
    has_seats = Seat.objects.filter(room=obj).exists()
    if has_seats and request.method == 'POST':
        messages.error(request, f'Cannot delete room "{obj.name}" — it still has seats.')
        return redirect('halls:room_list')
    if request.method == 'POST':
        name = obj.name
        obj.delete()
        messages.success(request, f'Room "{name}" deleted.')
        return redirect('halls:room_list')
    return render(request, 'halls/object_confirm_delete.html', {'object': obj, 'page_title': 'Delete Room', 'has_data': has_seats})

# ---------------- Seat ----------------
@login_required
def seat_list(request):
    halls = _visible_halls(request)
    q = (request.GET.get('q') or '').strip()
    qs = Seat.objects.filter(hall__in=halls).select_related('hall', 'room', 'room__floor', 'created_by')
    if q:
        qs = qs.filter(Q(seat_number__icontains=q) | Q(room__name__icontains=q) | Q(hall__name__icontains=q))
    paginator = CursorPaginator(qs, page_size=PAGE_SIZE, order_field='pk', reverse=True)
    page = paginator.page(request.GET.get('cursor'))
    params = request.GET.copy()
    params.pop('cursor', None)
    qs_str = params.urlencode()
    querystring = f'{qs_str}&' if qs_str else ''
    return render(request, 'halls/seat_list.html', {'page_obj': page, 'objects': page.object_list, 'querystring': querystring, 'q': q, 'page_title': 'My Seats'})

@login_required
def seat_add(request):
    halls = _visible_halls(request)
    if request.method == 'POST':
        form = ManagerSeatForm(request.POST, user=request.user)
        if form.is_valid():
            obj = form.save(commit=False)
            if obj.hall_id not in halls.values_list('pk', flat=True):
                messages.error(request, 'Invalid hall.')
                return redirect('halls:seat_list')
            obj.created_by = request.user
            obj.save()
            messages.success(request, f'Seat "{obj.seat_number}" created.')
            return redirect('halls:seat_list')
    else:
        form = ManagerSeatForm(user=request.user)
    return render(request, 'halls/object_form.html', {'form': form, 'page_title': 'Add Seat', 'heading': 'New Seat'})

@login_required
def seat_edit(request, pk):
    halls = _visible_halls(request)
    obj = get_object_or_404(Seat, pk=pk, hall__in=halls)
    _check_owner(obj, request.user)
    if _seat_in_use(obj):
        messages.error(request, f'Cannot edit seat "{obj.seat_label}" — it is in use (has assignments/slips/maintenance).')
        return redirect('halls:seat_list')
    if request.method == 'POST':
        form = ManagerSeatForm(request.POST, instance=obj, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, f'Seat "{obj.seat_number}" updated.')
            return redirect('halls:seat_list')
    else:
        form = ManagerSeatForm(instance=obj, user=request.user)
    return render(request, 'halls/object_form.html', {'form': form, 'page_title': 'Edit Seat', 'heading': f'Edit {obj.seat_label}'})

@login_required
def seat_delete(request, pk):
    halls = _visible_halls(request)
    obj = get_object_or_404(Seat, pk=pk, hall__in=halls)
    _check_owner(obj, request.user)
    from allocations.models import SeatAssignment, SeatAssignmentLog, SeatMaintenance, SeatMaintenanceLog
    has_data = (
        SeatAssignment.objects.filter(seat=obj).exists()
        or SeatMaintenance.objects.filter(seat=obj).exists()
        or SeatAssignmentLog.objects.filter(seat=obj).exists()
        or SeatMaintenanceLog.objects.filter(seat=obj).exists()
    )
    if has_data and request.method == 'POST':
        messages.error(request, f'Cannot delete seat "{obj.seat_label}" — it has assignments/maintenance history. Disable it instead (is_active).')
        return redirect('halls:seat_list')
    if request.method == 'POST':
        label = obj.seat_label
        obj.delete()
        messages.success(request, f'Seat "{label}" deleted.')
        return redirect('halls:seat_list')
    return render(request, 'halls/object_confirm_delete.html', {'object': obj, 'page_title': 'Delete Seat', 'has_data': has_data})
