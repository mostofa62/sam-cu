from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.db.models.deletion import ProtectedError
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.generic import (CreateView, DeleteView, FormView, ListView,
                                  UpdateView, View)

from accounts.models import ADMIN_GROUP_NAME
from allocations.forms import ImportAllocationsForm
from allocations.importer import import_allocations
from allocations.models import (AllocationCall, SeatAssignment,
                                SeatAssignmentLog, SeatReleaseReason)
from halls.models import Block, Floor, Hall, Room, Seat
from students.models import Student
from students.services import pull_students_from_external_system

from .forms import (BlockForm, FloorForm, HallForm, HallManagerForm,
                    ReleaseReasonForm, RoomForm, SeatForm, StudentForm)
from .pagination import CursorPaginator

User = get_user_model()

PAGE_SIZE = 25


class AdminPanelRequiredMixin:
    """Every admin-panel page requires a logged-in app administrator
    (superuser or member of the 'Admin' group)."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('accounts:login')
        if not request.user.is_app_admin:
            messages.error(request, 'You need administrator access to open that page.')
            return redirect('dashboard:home')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        """Expose success_url/back_url so shared form + delete templates always
        have a cancel target, even when a bound form re-renders with errors."""
        context = super().get_context_data(**kwargs)
        for attr in ('success_url', 'back_url'):
            value = getattr(self, attr, None)
            if value is not None:
                context.setdefault(attr, value)
        return context


class CursorFilterListView(AdminPanelRequiredMixin, View):
    """View with search (?q=), dropdown filters, and high-performance cursor pagination."""

    model = None
    template_name = None
    context_object_name = 'objects'
    page_size = PAGE_SIZE
    search_fields = ()
    hall_filter = False
    order_field = 'pk'
    reverse_order = True

    def get_queryset(self):
        qs = self.model.objects.all()
        q = (self.request.GET.get('q') or '').strip()
        if q and self.search_fields:
            conditions = Q()
            for field in self.search_fields:
                conditions |= Q(**{f'{field}__icontains': q})
            qs = qs.filter(conditions)
        if self.hall_filter:
            hall_id = self.request.GET.get('hall')
            if hall_id:
                qs = qs.filter(hall_id=hall_id)
        return qs

    def get_context_data(self, **kwargs):
        kwargs.setdefault('objects', kwargs.get('object_list'))
        return kwargs

    def get(self, request, *args, **kwargs):
        qs = self.get_queryset()
        paginator = CursorPaginator(
            qs,
            page_size=self.page_size,
            order_field=self.order_field,
            reverse=self.reverse_order,
        )
        cursor = request.GET.get('cursor')
        page_obj = paginator.page(cursor)

        params = request.GET.copy()
        params.pop('cursor', None)
        querystring = f'{params.urlencode()}&' if params else ''

        context = {
            'object_list': page_obj.object_list,
            'page_obj': page_obj,
            'cursor_paginated': True,
            'querystring': querystring,
            'q': (request.GET.get('q') or '').strip(),
            'halls': Hall.objects.all(),
            'selected_hall': request.GET.get('hall', ''),
        }
        context = self.get_context_data(**context)
        return render(request, self.template_name, context)


def guarded_delete(delete_view):
    """Keep release/assignment history intact: records referenced by logs
    cannot be deleted — surface that as a friendly message instead of a 500."""
    def form_valid(self, form):
        label = str(self.object)
        try:
            self.object.delete()
        except ProtectedError:
            messages.error(
                self.request,
                f'{label} has related records attached. History must be preserved, '
                'so it cannot be deleted.',
            )
            return redirect(self.success_url)
        messages.success(self.request, f'Deleted {self.object_verbose} “{label}”.')
        return redirect(self.success_url)
    delete_view.form_valid = form_valid
    return delete_view


# --------------------------------------------------------------------------- #
# JSON endpoint for dynamic dependent dropdowns (Hall -> Blocks, Floors, Rooms)
# --------------------------------------------------------------------------- #

def hall_children_json(request):
    """Return blocks, floors, and rooms belonging to a selected hall for dynamic form/filter selects."""
    if not request.user.is_authenticated or not request.user.is_app_admin:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    hall_id = request.GET.get('hall_id')
    if not hall_id:
        return JsonResponse({'blocks': [], 'floors': [], 'rooms': []})

    blocks = list(Block.objects.filter(hall_id=hall_id).values('id', 'name').order_by('name'))
    floors = list(Floor.objects.filter(hall_id=hall_id).values('id', 'name', 'block_id').order_by('name'))
    rooms = list(Room.objects.filter(hall_id=hall_id).values('id', 'name', 'floor_id').order_by('name'))
    return JsonResponse({'blocks': blocks, 'floors': floors, 'rooms': rooms})


# --------------------------------------------------------------------------- #
# Overview
# --------------------------------------------------------------------------- #

class IndexView(AdminPanelRequiredMixin, ListView):
    template_name = 'adminpanel/index.html'
    context_object_name = 'halls'
    paginate_by = None

    def get_queryset(self):
        return Hall.objects.all().order_by('name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Administration'
        context['hall_count'] = Hall.objects.count()
        context['block_count'] = Block.objects.count()
        context['floor_count'] = Floor.objects.count()
        context['room_count'] = Room.objects.count()
        context['seat_count'] = Seat.objects.count()
        context['manager_count'] = User.objects.filter(managed_hall__isnull=False).count()
        context['student_count'] = Student.objects.count()
        context['active_call'] = AllocationCall.active()
        context['call_count'] = AllocationCall.objects.count()
        context['active_assignments'] = SeatAssignment.objects.filter(is_active=True).count()
        context['log_count'] = SeatAssignmentLog.objects.count()
        context['admin_group'] = ADMIN_GROUP_NAME
        return context


# --------------------------------------------------------------------------- #
# Halls (Manage only halls: list, add, edit, delete)
# --------------------------------------------------------------------------- #

class HallListView(CursorFilterListView):
    model = Hall
    template_name = 'adminpanel/hall_list.html'
    search_fields = ('name', 'code')
    order_field = 'pk'
    reverse_order = False

    def get_queryset(self):
        return super().get_queryset().order_by('name')


class HallCreateView(AdminPanelRequiredMixin, CreateView):
    model = Hall
    form_class = HallForm
    template_name = 'adminpanel/object_form.html'
    success_url = reverse_lazy('adminpanel:hall_list')
    object_verbose = 'Hall'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title='Add Hall', heading='New hall')
        return context


class HallUpdateView(AdminPanelRequiredMixin, UpdateView):
    model = Hall
    form_class = HallForm
    template_name = 'adminpanel/object_form.html'
    success_url = reverse_lazy('adminpanel:hall_list')
    object_verbose = 'Hall'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title='Edit Hall', heading=f'Edit hall — {self.object.name}')
        return context


@guarded_delete
class HallDeleteView(AdminPanelRequiredMixin, DeleteView):
    model = Hall
    template_name = 'adminpanel/object_confirm_delete.html'
    success_url = reverse_lazy('adminpanel:hall_list')
    object_verbose = 'Hall'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title='Delete Hall',
                       warning=f'Blocks, floors, rooms and seats belonging to {self.object.name} are removed together with it.')
        return context


# --------------------------------------------------------------------------- #
# Blocks
# --------------------------------------------------------------------------- #

class BlockListView(CursorFilterListView):
    model = Block
    template_name = 'adminpanel/block_list.html'
    search_fields = ('name', 'hall__name')
    hall_filter = True
    order_field = 'pk'

    def get_queryset(self):
        return super().get_queryset().select_related('hall')


class BlockCreateView(AdminPanelRequiredMixin, CreateView):
    model = Block
    form_class = BlockForm
    template_name = 'adminpanel/object_form.html'
    success_url = reverse_lazy('adminpanel:block_list')
    object_verbose = 'Block'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title='Add Block', heading='New block')
        return context


class BlockUpdateView(AdminPanelRequiredMixin, UpdateView):
    model = Block
    form_class = BlockForm
    template_name = 'adminpanel/object_form.html'
    success_url = reverse_lazy('adminpanel:block_list')
    object_verbose = 'Block'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title='Edit Block', heading=f'Edit block — {self.object}')
        return context


@guarded_delete
class BlockDeleteView(AdminPanelRequiredMixin, DeleteView):
    model = Block
    template_name = 'adminpanel/object_confirm_delete.html'
    success_url = reverse_lazy('adminpanel:block_list')
    object_verbose = 'Block'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title='Delete Block',
                       warning=f'Floors, rooms and seats inside {self.object} are removed together with it.')
        return context


# --------------------------------------------------------------------------- #
# Floors
# --------------------------------------------------------------------------- #

class FloorListView(CursorFilterListView):
    model = Floor
    template_name = 'adminpanel/floor_list.html'
    search_fields = ('name', 'hall__name', 'block__name')
    hall_filter = True
    order_field = 'pk'

    def get_queryset(self):
        qs = super().get_queryset().select_related('hall', 'block')
        block_id = self.request.GET.get('block')
        if block_id:
            qs = qs.filter(block_id=block_id)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        hall_id = self.request.GET.get('hall')
        context['blocks'] = Block.objects.filter(hall_id=hall_id) if hall_id else Block.objects.none()
        context['selected_block'] = self.request.GET.get('block', '')
        return context


class FloorCreateView(AdminPanelRequiredMixin, CreateView):
    model = Floor
    form_class = FloorForm
    template_name = 'adminpanel/object_form.html'
    success_url = reverse_lazy('adminpanel:floor_list')
    object_verbose = 'Floor'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title='Add Floor', heading='New floor')
        return context


class FloorUpdateView(AdminPanelRequiredMixin, UpdateView):
    model = Floor
    form_class = FloorForm
    template_name = 'adminpanel/object_form.html'
    success_url = reverse_lazy('adminpanel:floor_list')
    object_verbose = 'Floor'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title='Edit Floor', heading=f'Edit floor — {self.object}')
        return context


@guarded_delete
class FloorDeleteView(AdminPanelRequiredMixin, DeleteView):
    model = Floor
    template_name = 'adminpanel/object_confirm_delete.html'
    success_url = reverse_lazy('adminpanel:floor_list')
    object_verbose = 'Floor'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title='Delete Floor',
                       warning=f'Rooms and seats on {self.object} are removed together with it.')
        return context


# --------------------------------------------------------------------------- #
# Rooms
# --------------------------------------------------------------------------- #

class RoomListView(CursorFilterListView):
    model = Room
    template_name = 'adminpanel/room_list.html'
    search_fields = ('name', 'floor__name', 'hall__name')
    hall_filter = True
    order_field = 'pk'

    def get_queryset(self):
        qs = super().get_queryset().select_related('hall', 'floor__block')
        floor_id = self.request.GET.get('floor')
        if floor_id:
            qs = qs.filter(floor_id=floor_id)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        hall_id = self.request.GET.get('hall')
        context['floors'] = Floor.objects.filter(hall_id=hall_id) if hall_id else Floor.objects.none()
        context['selected_floor'] = self.request.GET.get('floor', '')
        return context


class RoomCreateView(AdminPanelRequiredMixin, CreateView):
    model = Room
    form_class = RoomForm
    template_name = 'adminpanel/object_form.html'
    success_url = reverse_lazy('adminpanel:room_list')
    object_verbose = 'Room'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title='Add Room', heading='New room')
        return context


class RoomUpdateView(AdminPanelRequiredMixin, UpdateView):
    model = Room
    form_class = RoomForm
    template_name = 'adminpanel/object_form.html'
    success_url = reverse_lazy('adminpanel:room_list')
    object_verbose = 'Room'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title='Edit Room', heading=f'Edit room — {self.object.name}')
        return context


@guarded_delete
class RoomDeleteView(AdminPanelRequiredMixin, DeleteView):
    model = Room
    template_name = 'adminpanel/object_confirm_delete.html'
    success_url = reverse_lazy('adminpanel:room_list')
    object_verbose = 'Room'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title='Delete Room',
                       warning=f'Seats inside room {self.object.name} are removed together with it.')
        return context


# --------------------------------------------------------------------------- #
# Seats
# --------------------------------------------------------------------------- #

class SeatListView(CursorFilterListView):
    model = Seat
    template_name = 'adminpanel/seat_list.html'
    search_fields = ('seat_number', 'room__name', 'hall__name')
    hall_filter = True
    order_field = 'pk'

    def get_queryset(self):
        qs = super().get_queryset().select_related('room__floor__block', 'hall')
        room_id = self.request.GET.get('room')
        if room_id:
            qs = qs.filter(room_id=room_id)
        state = self.request.GET.get('state')
        if state == 'active':
            qs = qs.filter(is_active=True)
        elif state == 'disabled':
            qs = qs.filter(is_active=False)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        hall_id = self.request.GET.get('hall')
        context['rooms'] = Room.objects.filter(hall_id=hall_id) if hall_id else Room.objects.none()
        context['selected_room'] = self.request.GET.get('room', '')
        context['state'] = self.request.GET.get('state', '')

        # Annotate allotted flag for items on the current page
        assigned_ids = set(SeatAssignment.objects.filter(is_active=True).values_list('seat_id', flat=True))
        for seat in context.get('objects', []):
            seat.is_allotted = seat.pk in assigned_ids
        return context


class SeatCreateView(AdminPanelRequiredMixin, CreateView):
    model = Seat
    form_class = SeatForm
    template_name = 'adminpanel/object_form.html'
    success_url = reverse_lazy('adminpanel:seat_list')
    object_verbose = 'Seat'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title='Add Seat', heading='New seat')
        return context


class SeatUpdateView(AdminPanelRequiredMixin, UpdateView):
    model = Seat
    form_class = SeatForm
    template_name = 'adminpanel/object_form.html'
    success_url = reverse_lazy('adminpanel:seat_list')
    object_verbose = 'Seat'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title='Edit Seat', heading=f'Edit seat — {self.object.seat_label}')
        return context


@guarded_delete
class SeatDeleteView(AdminPanelRequiredMixin, DeleteView):
    model = Seat
    template_name = 'adminpanel/object_confirm_delete.html'
    success_url = reverse_lazy('adminpanel:seat_list')
    object_verbose = 'Seat'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title='Delete Seat',
                       warning=f'{self.object.full_label} will be permanently removed. Prefer deactivating a seat instead.')
        return context


# --------------------------------------------------------------------------- #
# Hall managers / Users
# --------------------------------------------------------------------------- #

class UserListView(CursorFilterListView):
    """User list.

    - Super Admin: sees ALL users (Superadmins, Admins, Hall Managers) with a role filter.
    - Regular Admin: sees ONLY Hall Managers (Admins and Superadmins are hidden).
    """

    model = User
    template_name = 'adminpanel/user_list.html'
    search_fields = ('full_name', 'email', 'phone', 'managed_hall__name')
    order_field = 'date_joined'
    reverse_order = True

    def get_queryset(self):
        qs = User.objects.all().select_related('managed_hall').prefetch_related('groups')
        q = (self.request.GET.get('q') or '').strip()
        if q:
            qs = qs.filter(
                Q(full_name__icontains=q) |
                Q(email__icontains=q) |
                Q(phone__icontains=q) |
                Q(managed_hall__name__icontains=q)
            )

        if not self.request.user.is_superuser:
            # Regular Admin: strictly hide Admins and Superusers; only show actual Hall Managers!
            qs = qs.filter(managed_hall__isnull=False, is_superuser=False).exclude(groups__name=ADMIN_GROUP_NAME)
        else:
            # Super Admin: can optionally filter by role
            role = self.request.GET.get('role')
            if role == 'superuser':
                qs = qs.filter(is_superuser=True)
            elif role == 'admin':
                qs = qs.filter(groups__name=ADMIN_GROUP_NAME, is_superuser=False)
            elif role == 'manager':
                qs = qs.filter(managed_hall__isnull=False, is_superuser=False).exclude(groups__name=ADMIN_GROUP_NAME)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        is_super = self.request.user.is_superuser
        context['is_super_admin'] = is_super
        context['page_title'] = 'Users & Hall Managers' if is_super else 'Hall Managers'
        context['selected_role'] = self.request.GET.get('role', '')
        return context


class UserCreateView(AdminPanelRequiredMixin, CreateView):
    model = User
    form_class = HallManagerForm
    template_name = 'adminpanel/object_form.html'
    success_url = reverse_lazy('adminpanel:user_list')
    object_verbose = 'Hall Manager'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title='Add Hall Manager', heading='New hall manager')
        return context


class UserUpdateView(AdminPanelRequiredMixin, UpdateView):
    model = User
    form_class = HallManagerForm
    template_name = 'adminpanel/object_form.html'
    success_url = reverse_lazy('adminpanel:user_list')
    object_verbose = 'Hall Manager'

    def dispatch(self, request, *args, **kwargs):
        target = self.get_object()
        # Regular admin cannot edit Superusers or Admins in the Admin group
        if not request.user.is_superuser and (target.is_superuser or target.in_admin_group):
            messages.error(request, 'You do not have permission to edit administrators.')
            return redirect('adminpanel:user_list')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title='Edit Hall Manager', heading=f'Edit user — {self.object}')
        return context


class UserDeleteView(AdminPanelRequiredMixin, DeleteView):
    model = User
    template_name = 'adminpanel/object_confirm_delete.html'
    success_url = reverse_lazy('adminpanel:user_list')
    object_verbose = 'User'

    def dispatch(self, request, *args, **kwargs):
        target = self.get_object()
        if target.pk == request.user.pk:
            messages.error(request, 'You cannot delete your own account.')
            return redirect(self.success_url)
        if not request.user.is_superuser and (target.is_superuser or target.in_admin_group):
            messages.error(request, 'You do not have permission to delete administrators.')
            return redirect(self.success_url)
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        name = str(self.object)
        self.object.delete()
        messages.success(self.request, f'Deleted user {name}.')
        return redirect(self.success_url)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title='Delete User',
                       warning=f'The account of {self.object} loses access immediately.')
        return context


# --------------------------------------------------------------------------- #
# Allocation calls
# --------------------------------------------------------------------------- #

class CallListView(AdminPanelRequiredMixin, FormView):
    template_name = 'adminpanel/call_list.html'
    form_class = ImportAllocationsForm
    success_url = reverse_lazy('adminpanel:call_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Allocation Calls'
        context['calls'] = AllocationCall.objects.annotate(allotment_total=Count('allotments'))
        context['active_call'] = AllocationCall.active()
        return context

    def post(self, request, *args, **kwargs):
        action = request.POST.get('action', 'import')
        if action == 'activate_call':
            return self._activate_call(request)
        if action == 'deactivate_call':
            return self._deactivate_call(request)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        try:
            summary = import_allocations(
                form.cleaned_data['csv_file'], acting_user=self.request.user,
            )
        except ValidationError as exc:
            for message in exc.messages:
                form.add_error(None, message)
            return self.form_invalid(form)
        label = f"Call {summary['call_id']}"
        if summary.get('reused'):
            messages.info(self.request, f'{label} re-imported — rows updated; activation status unchanged.')
        else:
            messages.success(self.request, f"{label} imported with {summary['rows']} allotment row(s).")
        return redirect(self.success_url)

    def _activate_call(self, request):
        call = AllocationCall.objects.filter(call_id=(request.POST.get('call_id') or '').strip()).first()
        if call is None:
            messages.error(request, 'That allocation call does not exist.')
            return redirect(self.success_url)
        with transaction.atomic():
            AllocationCall.objects.exclude(pk=call.pk).filter(is_active=True).update(is_active=False)
            if not call.is_active:
                call.is_active = True
                call.save(update_fields=['is_active'])
        messages.success(request, f'Call {call.call_id} is now the active allocation call.')
        return redirect(self.success_url)

    def _deactivate_call(self, request):
        call = AllocationCall.objects.filter(call_id=(request.POST.get('call_id') or '').strip()).first()
        if call is None:
            messages.error(request, 'That allocation call does not exist.')
        elif call.is_active:
            call.is_active = False
            call.save(update_fields=['is_active'])
            messages.warning(request, f'Call {call.call_id} deactivated — no call is active now.')
        return redirect(self.success_url)


# --------------------------------------------------------------------------- #
# Students (Cursor pagination)
# --------------------------------------------------------------------------- #

class StudentListView(CursorFilterListView):
    model = Student
    template_name = 'adminpanel/student_list.html'
    search_fields = ('student_id', 'name_en', 'name_bn', 'session', 'phone', 'nid', 'subject_code', 'subject')
    order_field = 'student_id'
    reverse_order = False

    STATUS_CODES = {'active': 1, 'suspended': 2, 'cancelled': 3, 'graduated': 4}

    def get_queryset(self):
        qs = super().get_queryset()
        state = self.request.GET.get('state')
        if state in self.STATUS_CODES:
            qs = qs.filter(student_status=self.STATUS_CODES[state])
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['state'] = self.request.GET.get('state', '')
        qs = self.get_queryset()
        context['total_students'] = Student.objects.count()
        # filtered count respects search + status filters; cheap count() on filtered QS
        try:
            context['filtered_count'] = qs.count()
        except Exception:
            context['filtered_count'] = None
        context['page_title'] = 'Students'
        return context


class StudentCreateView(AdminPanelRequiredMixin, CreateView):
    model = Student
    form_class = StudentForm
    template_name = 'adminpanel/object_form.html'
    success_url = reverse_lazy('adminpanel:student_list')
    object_verbose = 'Student'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title='Add Student', heading='New student record')
        return context


class StudentUpdateView(AdminPanelRequiredMixin, UpdateView):
    model = Student
    form_class = StudentForm
    template_name = 'adminpanel/object_form.html'
    success_url = reverse_lazy('adminpanel:student_list')
    object_verbose = 'Student'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title='Edit Student', heading=f'Edit student — {self.object.student_id}')
        return context


class StudentDeleteView(AdminPanelRequiredMixin, DeleteView):
    model = Student
    template_name = 'adminpanel/object_confirm_delete.html'
    success_url = reverse_lazy('adminpanel:student_list')
    object_verbose = 'Student'

    def form_valid(self, form):
        student_id = self.object.student_id
        self.object.delete()
        messages.success(self.request, f'Deleted student {student_id}.')
        return redirect(self.success_url)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title='Delete Student',
                       warning=f'Student record {self.object.student_id} is removed from master data. Past seat assignments keep their history.')
        return context


class StudentPullView(AdminPanelRequiredMixin, View):
    """Pull fresh student rows from the external student system into master data."""

    def post(self, request):
        created, updated = pull_students_from_external_system()
        messages.success(
            request,
            f'Pull complete — {created} new student(s), {updated} updated from the external system.',
        )
        return redirect('adminpanel:student_list')


# --------------------------------------------------------------------------- #
# Assignments / logs / release reasons (Cursor pagination)
# --------------------------------------------------------------------------- #

class AssignmentListView(CursorFilterListView):
    model = SeatAssignment
    template_name = 'adminpanel/assignment_list.html'
    search_fields = ('student_id', 'seat__seat_number', 'seat__room__name')
    hall_filter = True
    order_field = 'pk'
    reverse_order = True

    def get_queryset(self):
        qs = super().get_queryset().select_related(
            'seat__room__floor__block', 'seat__hall', 'released_reason',
        )
        state = self.request.GET.get('state')
        if state == 'active':
            qs = qs.filter(is_active=True)
        elif state == 'released':
            qs = qs.filter(is_active=False)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['state'] = self.request.GET.get('state', '')
        return context


class LogListView(CursorFilterListView):
    model = SeatAssignmentLog
    template_name = 'adminpanel/log_list.html'
    search_fields = ('student_id', 'note')
    order_field = 'pk'
    reverse_order = True

    def get_queryset(self):
        qs = super().get_queryset().select_related(
            'seat__hall', 'release_reason', 'performed_by',
        )
        action = self.request.GET.get('action')
        if action in ('assigned', 'released'):
            qs = qs.filter(action=action)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['action'] = self.request.GET.get('action', '')
        return context


class ReasonListView(CursorFilterListView):
    model = SeatReleaseReason
    template_name = 'adminpanel/reason_list.html'
    search_fields = ('name',)
    order_field = 'pk'
    reverse_order = False


class ReasonCreateView(AdminPanelRequiredMixin, CreateView):
    model = SeatReleaseReason
    form_class = ReleaseReasonForm
    template_name = 'adminpanel/object_form.html'
    success_url = reverse_lazy('adminpanel:reason_list')
    object_verbose = 'Seat Release Reason'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title='Add Release Reason', heading='New seat release reason')
        return context


class ReasonUpdateView(AdminPanelRequiredMixin, UpdateView):
    model = SeatReleaseReason
    form_class = ReleaseReasonForm
    template_name = 'adminpanel/object_form.html'
    success_url = reverse_lazy('adminpanel:reason_list')
    object_verbose = 'Seat Release Reason'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title='Edit Release Reason', heading=f'Edit reason — {self.object.name}')
        return context


class ReasonDeleteView(AdminPanelRequiredMixin, DeleteView):
    model = SeatReleaseReason
    template_name = 'adminpanel/object_confirm_delete.html'
    success_url = reverse_lazy('adminpanel:reason_list')
    object_verbose = 'Seat Release Reason'

    def form_valid(self, form):
        name = self.object.name
        self.object.delete()
        messages.success(self.request, f'Deleted release reason "{name}".')
        return redirect(self.success_url)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title='Delete Release Reason',
                       warning=f'“{self.object.name}” disappears from the release dropdown. Past releases keep their recorded reason.')
        return context
