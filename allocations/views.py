from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render, reverse
from django.utils import timezone

from halls.models import Room, Seat
from students.models import Student

from .forms import (AssignForm, ImportAllocationsForm, MaintenanceForm,
                     MaintenanceReasonForm, ReleaseReasonForm, ResolveRequestForm,
                     RevokeForm)
from .importer import import_allocations
from .models import (AllocationCall, HallAllocation, OrderChoices, ResolveRequest,
                     ResolveStatus, ResolveType, SeatAssignment,
                     SeatAssignmentLog, SeatMaintenance, SeatMaintenanceLog,
                     SeatMaintenanceReason, SeatReleaseReason)
from .services import (approve_resolve_request, assign_seat, build_resolve_snapshot,
                       is_assignment_blocked, put_seat_under_maintenance,
                       reject_resolve_request, remove_seat_from_maintenance,
                       revoke_seat, validate_seat_assignable)


def _student_record(student_id):
    """Master-data record from the students table for the confirmation preview."""
    return Student.objects.filter(student_id=student_id).first()


def _allotment_record(student_id):
    """Merit-list allotment of the student in the currently active call (or None)."""
    active_call = AllocationCall.active()
    if active_call is None:
        return None
    return HallAllocation.objects.filter(call=active_call, student_id=student_id).first()


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
                        f'as {assignment.get_order_display()}. Now create the assign slip / invoice.',
                    )
                    return redirect('slips:from_assignment', pk=assignment.pk)
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
                    allotment = validate_seat_assignable(seat, student_id, acting_user=request.user)
                except ValidationError as e:
                    form.add_error('seat', e)
                else:
                    preview = {
                        'student': _student_record(student_id),
                        'allotment': allotment,
                        'active_call': AllocationCall.active(),
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
                    messages.success(request, f'Released {len(released)} seat assignment(s). Now create the release slip / invoice.')
                    # Jump to release slip creation with student prefilled
                    return redirect(f"/slips/create/release/?student_id={student_id}")
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
    q = (request.GET.get('q') or '').strip()
    log_q = (request.GET.get('log_q') or '').strip()

    assignments_qs = SeatAssignment.objects.filter(
        is_active=True, seat__hall__in=visible_halls,
    ).select_related(
        'seat__room__floor__block', 'seat__room__floor', 'seat__hall',
    )
    if q:
        assignments_qs = assignments_qs.filter(
            Q(student_id__icontains=q) | Q(seat__seat_number__icontains=q) | Q(seat__room__name__icontains=q) | Q(seat__hall__name__icontains=q)
        )

    logs_qs = SeatAssignmentLog.objects.filter(
        seat__hall__in=visible_halls,
    ).select_related('seat__room', 'performed_by', 'release_reason')
    if log_q:
        logs_qs = logs_qs.filter(
            Q(student_id__icontains=log_q) | Q(seat__seat_number__icontains=log_q) | Q(seat__room__name__icontains=log_q) | Q(seat__hall__name__icontains=log_q) | Q(action__icontains=log_q) | Q(performed_by__full_name__icontains=log_q) | Q(release_reason__name__icontains=log_q)
        )

    from adminpanel.pagination import CursorPaginator

    # Cursor pagination for assignments
    assign_paginator = CursorPaginator(assignments_qs, page_size=20, order_field='pk', reverse=True)
    assign_page = assign_paginator.page(request.GET.get('cursor'))

    # Cursor pagination for logs
    log_paginator = CursorPaginator(logs_qs, page_size=20, order_field='pk', reverse=True)
    log_page = log_paginator.page(request.GET.get('log_cursor'))

    # Build querystrings preserving search
    from django.http import QueryDict

    def build_qs(exclude):
        params = request.GET.copy()
        for k in exclude:
            params.pop(k, None)
        qs = params.urlencode()
        return f'{qs}&' if qs else ''

    assign_querystring = build_qs(['cursor'])
    log_querystring = build_qs(['log_cursor'])

    # Pending resolve block: collect assignment ids that are locked
    pending_ids = set(
        ResolveRequest.objects.filter(status=ResolveStatus.PENDING, assignment__isnull=False)
        .filter(assignment__seat__hall__in=visible_halls)
        .values_list('assignment_id', flat=True)
    )
    pending_count = ResolveRequest.objects.filter(status=ResolveStatus.PENDING).filter(
        Q(hall__in=visible_halls) | Q(seat__hall__in=visible_halls)
    ).count() if not request.user.is_app_admin else ResolveRequest.objects.filter(status=ResolveStatus.PENDING).count()

    # Enrich Recent Activity logs with their underlying SeatAssignment (active or released)
    # so a manager can request resolve directly from a release log even when the
    # assignment is inactive (is_active=False) and thus not in the top table.
    logs_enriched = list(log_page.object_list)
    if logs_enriched:
        # Bulk lookup: (student_id, seat_id) -> latest SeatAssignment (active or not)
        log_student_ids = {l.student_id for l in logs_enriched if l.student_id}
        log_seat_ids = {l.seat_id for l in logs_enriched if l.seat_id}
        # Fetch all candidate assignments in one query
        cand_assigns = list(
            SeatAssignment.objects.filter(
                student_id__in=log_student_ids,
                seat_id__in=log_seat_ids,
                seat__hall__in=visible_halls,
            ).select_related('seat__hall', 'seat__room').order_by('-assigned_at', '-pk')
        )
        # Build lookup: keep first (latest) per (student_id, seat_id)
        assign_lookup = {}
        for a in cand_assigns:
            key = (a.student_id, a.seat_id)
            if key not in assign_lookup:
                assign_lookup[key] = a
        for log in logs_enriched:
            key = (log.student_id, log.seat_id)
            target = assign_lookup.get(key)
            # Attach for template: log.resolve_assignment / log.resolve_blocked
            log.resolve_assignment = target  # may be None if already deleted
            log.resolve_blocked = target.pk in pending_ids if target else False
    else:
        logs_enriched = []

    context = {
        'page_title': 'Active Assignments',
        'assignments': assign_page.object_list,
        'assign_page': assign_page,
        'assign_querystring': assign_querystring,
        'q': q,
        'logs': logs_enriched,
        'log_page': log_page,
        'log_querystring': log_querystring,
        'log_q': log_q,
        'release_reasons': SeatReleaseReason.objects.filter(is_active=True),
        'pending_ids': pending_ids,
        'pending_count': pending_count,
    }
    return render(request, 'allocations/assignments.html', context)


@login_required
def revoke_assignment(request, pk):
    assignment = get_object_or_404(
        SeatAssignment.objects.select_related('seat__room__floor__block', 'seat__hall'),
        pk=pk, is_active=True,
        seat__hall__in=request.user.visible_halls(),
    )
    # Block if pending resolve request exists for this assignment
    if is_assignment_blocked(assignment):
        messages.error(request, f'Assignment {assignment.student_id} @ {assignment.seat.seat_label} is locked — a pending resolve request exists. Wait for admin to resolve.')
        return redirect('allocations:active_assignments')
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
            messages.success(request, f'Released {assignment.student_id} from {assignment.seat.seat_label}. Now create the release slip.')
        except ValidationError as e:
            messages.error(request, str(e))
            return redirect('allocations:revoke_assignment', pk=pk)
        return redirect(f"/slips/create/release/?student_id={assignment.student_id}")

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
def maintenance_list(request):
    visible_halls = request.user.visible_halls()
    q = (request.GET.get('q') or '').strip()
    log_q = (request.GET.get('log_q') or '').strip()
    past_q = (request.GET.get('past_q') or '').strip()

    active_qs = SeatMaintenance.objects.filter(
        is_active=True, seat__hall__in=visible_halls,
    ).select_related('seat__room__floor__block', 'seat__hall', 'started_by', 'ended_by', 'maintenance_reason')
    if q:
        active_qs = active_qs.filter(
            Q(seat__seat_number__icontains=q) | Q(seat__room__name__icontains=q) | Q(seat__hall__name__icontains=q) | Q(reason__icontains=q) | Q(note__icontains=q) | Q(started_by__full_name__icontains=q) | Q(maintenance_reason__name__icontains=q)
        )

    past_qs = SeatMaintenance.objects.filter(
        is_active=False, seat__hall__in=visible_halls,
    ).select_related('seat__room__floor__block', 'seat__hall', 'started_by', 'ended_by', 'maintenance_reason').prefetch_related('logs')
    if past_q:
        past_qs = past_qs.filter(
            Q(seat__seat_number__icontains=past_q) | Q(seat__room__name__icontains=past_q) | Q(seat__hall__name__icontains=past_q) | Q(reason__icontains=past_q) | Q(note__icontains=past_q) | Q(started_by__full_name__icontains=past_q) | Q(ended_by__full_name__icontains=past_q) | Q(maintenance_reason__name__icontains=past_q)
        )

    logs_qs = SeatMaintenanceLog.objects.filter(
        seat__hall__in=visible_halls,
    ).select_related('seat__room', 'performed_by', 'maintenance')
    if log_q:
        logs_qs = logs_qs.filter(
            Q(seat__seat_number__icontains=log_q) | Q(seat__room__name__icontains=log_q) | Q(seat__hall__name__icontains=log_q) | Q(reason__icontains=log_q) | Q(note__icontains=log_q) | Q(performed_by__full_name__icontains=log_q) | Q(action__icontains=log_q)
        )

    from adminpanel.pagination import CursorPaginator

    active_paginator = CursorPaginator(active_qs, page_size=20, order_field='pk', reverse=True)
    active_page = active_paginator.page(request.GET.get('cursor'))

    past_paginator = CursorPaginator(past_qs, page_size=20, order_field='pk', reverse=True)
    past_page = past_paginator.page(request.GET.get('past_cursor'))

    logs_paginator = CursorPaginator(logs_qs, page_size=20, order_field='pk', reverse=True)
    logs_page = logs_paginator.page(request.GET.get('log_cursor'))

    def build_qs(exclude):
        params = request.GET.copy()
        for k in exclude:
            params.pop(k, None)
        qs = params.urlencode()
        return f'{qs}&' if qs else ''

    context = {
        'page_title': 'Seat Maintenance',
        'active_records': active_page.object_list,
        'active_page': active_page,
        'active_querystring': build_qs(['cursor']),
        'q': q,
        'past_records': past_page.object_list,
        'past_page': past_page,
        'past_querystring': build_qs(['past_cursor']),
        'past_q': past_q,
        'logs': logs_page.object_list,
        'logs_page': logs_page,
        'logs_querystring': build_qs(['log_cursor']),
        'log_q': log_q,
    }
    return render(request, 'allocations/maintenance_list.html', context)


@login_required
def maintenance_put(request):
    visible_halls = request.user.visible_halls()
    preview = None
    if request.method == 'POST':
        action = request.POST.get('action', 'preview')
        form = MaintenanceForm(request.POST, user=request.user)
        if form.is_valid():
            seat = form.cleaned_data['seat']
            reason = form.cleaned_data['reason']  # SeatMaintenanceReason instance
            note = form.cleaned_data['note'].strip()
            started_at = form.cleaned_data['started_at']
            ended_at = form.cleaned_data['ended_at']
            if action == 'confirm':
                try:
                    record = put_seat_under_maintenance(
                        seat=seat, reason=reason, note=note, performed_by=request.user,
                        started_at=started_at, ended_at=ended_at,
                    )
                    window = f' from {started_at.strftime("%d %b %Y %H:%M")}'
                    if ended_at:
                        window += f' to {ended_at.strftime("%d %b %Y %H:%M")}'
                    messages.success(request, f'Seat {record.seat.seat_label} put on hold{window}. Reason: {reason.name}')
                    return redirect('allocations:maintenance_list')
                except ValidationError as e:
                    form.add_error('seat', e)
            elif action == 'edit':
                pass
            else:
                # Preview — confirm details before committing
                preview = {
                    'seat': seat,
                    'reason': reason,
                    'note': note,
                    'started_at': started_at,
                    'ended_at': ended_at,
                }
    else:
        form = MaintenanceForm(user=request.user)

    context = {
        'page_title': 'Put Seat on Maintenance',
        'form': form,
        'halls': visible_halls,
        'single_hall': form.single_hall,
        'preview': preview,
    }
    return render(request, 'allocations/maintenance_put.html', context)


@login_required
def maintenance_remove(request, pk):
    visible_halls = request.user.visible_halls()
    record = get_object_or_404(
        SeatMaintenance.objects.select_related('seat__room__floor__block', 'seat__hall', 'started_by'),
        pk=pk, is_active=True, seat__hall__in=visible_halls,
    )
    if request.method == 'POST':
        note = (request.POST.get('note') or '').strip()
        try:
            removed = remove_seat_from_maintenance(
                seat=record.seat, performed_by=request.user, note=note,
            )
            messages.success(request, f'Seat {removed.seat.seat_label} removed from hold.')
        except ValidationError as e:
            messages.error(request, str(e))
            return redirect('allocations:maintenance_remove', pk=pk)
        return redirect('allocations:maintenance_list')

    context = {
        'page_title': 'Remove from Maintenance',
        'record': record,
    }
    return render(request, 'allocations/maintenance_remove.html', context)


# --------------------------------------------------------------------------- #
# Maintenance Reasons — hall manager can add, edit own; delete admin-only
# --------------------------------------------------------------------------- #

@login_required
def maintenance_reason_list(request):
    reasons = SeatMaintenanceReason.objects.all().order_by('sort_order', 'id')
    context = {
        'page_title': 'Maintenance Reasons',
        'reasons': reasons,
    }
    return render(request, 'allocations/maintenance_reason_list.html', context)


@login_required
def maintenance_reason_add(request):
    if request.method == 'POST':
        form = MaintenanceReasonForm(request.POST)
        if form.is_valid():
            reason = form.save(commit=False)
            reason.created_by = request.user
            reason.save()
            messages.success(request, f'Maintenance reason “{reason.name}” added.')
            return redirect('allocations:maintenance_reason_list')
    else:
        form = MaintenanceReasonForm()
    return render(request, 'allocations/maintenance_reason_form.html', {
        'page_title': 'Add Maintenance Reason',
        'form': form,
    })


@login_required
def maintenance_reason_edit(request, pk):
    reason = get_object_or_404(SeatMaintenanceReason, pk=pk)
    if not reason.is_editable_by(request.user):
        messages.error(request, 'You can only edit your own maintenance reasons. Default/system reasons can only be edited by administrators.')
        return redirect('allocations:maintenance_reason_list')
    if request.method == 'POST':
        form = MaintenanceReasonForm(request.POST, instance=reason)
        if form.is_valid():
            form.save()
            messages.success(request, f'Maintenance reason “{reason.name}” updated.')
            return redirect('allocations:maintenance_reason_list')
    else:
        form = MaintenanceReasonForm(instance=reason)
    return render(request, 'allocations/maintenance_reason_form.html', {
        'page_title': 'Edit Maintenance Reason',
        'form': form,
        'reason': reason,
    })


# --------------------------------------------------------------------------- #
# Release Reasons — hall manager: see all, add, edit own; no delete if used
# --------------------------------------------------------------------------- #

@login_required
def release_reason_list(request):
    reasons = SeatReleaseReason.objects.all().order_by('sort_order', 'id')
    context = {
        'page_title': 'Release Reasons',
        'reasons': reasons,
    }
    return render(request, 'allocations/release_reason_list.html', context)


@login_required
def release_reason_add(request):
    if request.method == 'POST':
        form = ReleaseReasonForm(request.POST)
        if form.is_valid():
            reason = form.save(commit=False)
            reason.created_by = request.user
            reason.save()
            messages.success(request, f'Release reason “{reason.name}” added.')
            return redirect('allocations:release_reason_list')
    else:
        form = ReleaseReasonForm()
    return render(request, 'allocations/release_reason_form.html', {
        'page_title': 'Add Release Reason',
        'form': form,
    })


@login_required
def release_reason_edit(request, pk):
    reason = get_object_or_404(SeatReleaseReason, pk=pk)
    if not reason.is_editable_by(request.user):
        messages.error(request, 'You can only edit your own release reasons. Default/system reasons can only be edited by administrators.')
        return redirect('allocations:release_reason_list')
    if request.method == 'POST':
        form = ReleaseReasonForm(request.POST, instance=reason)
        if form.is_valid():
            form.save()
            messages.success(request, f'Release reason “{reason.name}” updated.')
            return redirect('allocations:release_reason_list')
    else:
        form = ReleaseReasonForm(instance=reason)
    return render(request, 'allocations/release_reason_form.html', {
        'page_title': 'Edit Release Reason',
        'form': form,
        'reason': reason,
    })


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


@login_required
def import_allocations_view(request):
    """(App admins only) Upload a merit-list allocation CSV and manage calls.

    The imported call becomes the single active one. Administrators (superusers
    or members of the 'Admin' group) can also re-activate any previously
    imported call by hand.
    """
    if not request.user.is_app_admin:
        messages.info(
            request,
            'Allocation files are imported by administrators only — showing your hall allotments instead.',
        )
        return redirect('allocations:allotments')

    form = ImportAllocationsForm()
    summary = None

    if request.method == 'POST':
        action = request.POST.get('action', 'import')
        if action == 'activate_call':
            _activate_call(request)
        else:
            form = ImportAllocationsForm(request.POST, request.FILES)
            if form.is_valid():
                try:
                    summary = import_allocations(
                        request.FILES['csv_file'],
                        acting_user=request.user,
                    )
                    call_label = f"Call {summary['call_id']}"
                    if summary.get('auto_activated'):
                        messages.success(
                            request,
                            f'{call_label} imported and activated automatically as the first allocation call.',
                        )
                    elif summary.get('reused'):
                        messages.success(
                            request,
                            f'{call_label} re-imported — rows updated; activation status unchanged.',
                        )
                    else:
                        messages.warning(
                            request,
                            f'{call_label} imported but left INACTIVE — review it, then press '
                            f'"Set Active" to make it the allocation source for assignments.',
                        )
                    form = ImportAllocationsForm()
                except ValidationError as exc:
                    for message in exc.messages:
                        form.add_error(None, message)

    context = {
        'page_title': 'Import Allocations',
        'form': form,
        'summary': summary,
        'active_call': AllocationCall.active(),
        'calls': AllocationCall.objects.all()[:10],
    }
    return render(request, 'allocations/import.html', context)


def _activate_call(request):
    """Manually make an existing call the single active one (admin action)."""
    call_id = (request.POST.get('call_id') or '').strip()
    try:
        call = AllocationCall.objects.get(call_id=call_id)
    except AllocationCall.DoesNotExist:
        messages.error(request, f'No allocation call "{call_id}" exists.')
        return
    with transaction.atomic():
        AllocationCall.objects.exclude(pk=call.pk).filter(is_active=True).update(is_active=False)
        if not call.is_active:
            call.is_active = True
            call.save(update_fields=['is_active'])
    messages.success(request, f'Call {call.call_id} is now the active allocation call.')


@login_required
def allotments(request):
    """Read-only, call-wise merit-list allotments scoped to the viewer's halls.

    Hall managers see only rows allotted to the hall they manage; app admins
    (superusers / Admin group) see every hall. A call is selectable via
    ?call=YYYYNN and defaults to the active one.
    """
    visible_codes = list(request.user.visible_halls().exclude(code__isnull=True)
                         .values_list('code', flat=True))
    scope_q = Q(allotments__hall_code__in=visible_codes)
    calls = (AllocationCall.objects
             .annotate(rows_in_scope=Count('allotments', filter=scope_q))
             .order_by('-year', '-sequence'))
    if not request.user.is_app_admin:
        calls = calls.filter(rows_in_scope__gt=0)

    selected = None
    raw = request.GET.get('call')
    if raw:
        selected = calls.filter(call_id=raw).first()
    if selected is None:
        selected = calls.filter(is_active=True).first() or calls.first()

    q = (request.GET.get('q') or '').strip()
    allotment_page = None
    allotment_rows = []
    allotment_querystring = ''
    if selected is not None:
        qs = HallAllocation.objects.filter(call=selected, hall_code__in=visible_codes)
        if q:
            # also match student name/subject via Student table
            matching_ids = Student.objects.filter(
                Q(name_en__icontains=q) | Q(subject__icontains=q) | Q(subject_code__icontains=q)
            ).values_list('student_id', flat=True)
            qs = qs.filter(Q(student_id__icontains=q) | Q(hall_code__icontains=q) | Q(student_id__in=matching_ids))

        # CSV export should respect search as well
        if request.GET.get('export') == 'csv':
            rows = list(qs.select_related('call').order_by('student_id'))
            student_map = {
                s.student_id: s
                for s in Student.objects.filter(
                    student_id__in=[a.student_id for a in rows]
                ).only('student_id', 'name_en', 'subject_code', 'subject')
            }
            for a in rows:
                stu = student_map.get(a.student_id)
                a.student_name = stu.name_en if stu else None
                a.subject_code = stu.subject_code if stu else None
                a.subject = stu.subject if stu else None
            import csv
            from django.http import HttpResponse
            resp = HttpResponse(content_type='text/csv')
            resp['Content-Disposition'] = f'attachment; filename="allotments_{selected.call_id}.csv"'
            w = csv.writer(resp)
            w.writerow(['student_id', 'student_name', 'subject_code', 'subject', 'hall_code', 'call_id'])
            for a in rows:
                w.writerow([a.student_id, a.student_name or '', a.subject_code or '', a.subject or '', a.hall_code, selected.call_id])
            return resp

        from adminpanel.pagination import CursorPaginator
        paginator = CursorPaginator(qs, page_size=30, order_field='student_id', reverse=False)
        allotment_page = paginator.page(request.GET.get('cursor'))
        allotment_rows = list(allotment_page.object_list)
        # enrich with student details for current page only
        student_map = {
            s.student_id: s
            for s in Student.objects.filter(
                student_id__in=[a.student_id for a in allotment_rows]
            ).only('student_id', 'name_en', 'subject_code', 'subject')
        }
        for allotment in allotment_rows:
            stu = student_map.get(allotment.student_id)
            allotment.student_name = stu.name_en if stu else None
            allotment.subject_code = stu.subject_code if stu else None
            allotment.subject = stu.subject if stu else None

        params = request.GET.copy()
        params.pop('cursor', None)
        qs_str = params.urlencode()
        allotment_querystring = f'{qs_str}&' if qs_str else ''

    context = {
        'page_title': 'Hall Allotments',
        'calls': calls,
        'selected_call': selected,
        'allotments': allotment_rows,
        'allotment_page': allotment_page,
        'allotment_querystring': allotment_querystring,
        'q': q,
        'active_call': AllocationCall.active(),
    }
    return render(request, 'allocations/allotments.html', context)


@login_required
def delete_allotments(request):
    """(App admins only) Remove mistakenly imported allotment row(s).

    Expects a POST with ``ids`` (comma-separated HallAllocation pks). The UI
    asks for an explicit SweetAlert confirmation before submitting, and the
    success message repeats exactly what was removed.
    """
    if not request.user.is_app_admin:
        messages.error(request, 'Only administrators can delete allotment rows.')
        return redirect('allocations:allotments')
    if request.method != 'POST':
        return redirect('allocations:allotments')

    # Checkboxes arrive as REPEATED keys (ids=3&ids=7&ids=9) — get() would
    # return only the last one and silently drop the rest of the selection.
    # Accept both repeated keys and comma-joined strings.
    parsed = set()
    for value in request.POST.getlist('ids'):
        for part in str(value).split(','):
            part = part.strip()
            if part.isdigit():
                parsed.add(int(part))
    ids = sorted(parsed)
    if not ids:
        messages.error(request, 'No allotment rows were selected for deletion.')
        return redirect('allocations:allotments')

    rows = list(
        HallAllocation.objects.filter(pk__in=ids)
        .select_related('call')
        .order_by('call__call_id', 'student_id')
    )
    references = [f'{row.student_id} (call {row.call.call_id}, hall {row.hall_code})'
                  for row in rows]
    shown = ', '.join(references[:5]) + ('…' if len(references) > 5 else '')
    for row in rows:
        row.delete()
    messages.success(request, f'Deleted {len(rows)} allotment row(s): {shown}')

    next_call = (request.POST.get('next_call') or '').strip()
    if AllocationCall.CALL_ID_REGEX.match(next_call):
        return redirect(f"{reverse('allocations:allotments')}?call={next_call}")
    return redirect('allocations:allotments')


# --------------------------------------------------------------------------- #
# Resolve Requests – hall manager requests admin to delete mistaken assignment
# --------------------------------------------------------------------------- #

@login_required
def resolve_request_create(request, pk):
    """Hall manager creates a resolve request for a SeatAssignment (any status)."""
    assignment = get_object_or_404(
        SeatAssignment.objects.select_related('seat__room__floor__block', 'seat__hall'),
        pk=pk,
        seat__hall__in=request.user.visible_halls(),
    )
    if is_assignment_blocked(assignment):
        messages.error(request, f'Assignment {assignment.student_id} @ {assignment.seat.seat_label} already has a pending resolve request.')
        return redirect('allocations:active_assignments')
    # Allow both active and released to be requested; if released, still block
    if request.method == 'POST':
        form = ResolveRequestForm(request.POST)
        if form.is_valid():
            try:
                snapshot = build_resolve_snapshot(assignment)
            except Exception:
                snapshot = {}
            # Enrich snapshot with requester info (both ISO + display)
            now = timezone.now()
            snapshot['requested_by'] = str(request.user)
            snapshot['requested_at'] = now.isoformat()
            try:
                snapshot['requested_at_display'] = timezone.localtime(now).strftime('%d %b %Y, %I:%M %p')
            except Exception:
                snapshot['requested_at_display'] = snapshot['requested_at']
            req_type = form.cleaned_data['request_type']
            # Auto-infer if not matching assignment state? keep user choice
            resolve_req = ResolveRequest(
                request_type=req_type,
                hall=assignment.seat.hall,
                seat=assignment.seat,
                student_id=assignment.student_id,
                assignment=assignment,
                reason=form.cleaned_data['reason'],
                requested_by=request.user,
                snapshot=snapshot,
            )
            try:
                resolve_req.save()
            except Exception as e:
                # Handle unique constraint violation (race)
                messages.error(request, f'Could not create request: {e}')
                return redirect('allocations:resolve_list')
            messages.success(request, f'Resolve request created for {assignment.student_id} @ {assignment.seat.seat_label}. Awaiting admin approval. Row is now locked.')
            return redirect('allocations:resolve_list')
    else:
        # Default type based on assignment state, but allow explicit override from
        # Recent Activity log (action=assigned|released) via ?log_action=assigned.
        # This is needed because an assigned log may map to an assignment that is
        # now released (inactive), so basing solely on assignment.is_active would
        # incorrectly preselect RELEASE for an assigned mistake.
        log_action = (request.GET.get('log_action') or '').strip().lower()
        if log_action in ('assigned', 'assign'):
            initial_type = ResolveType.ASSIGN
        elif log_action in ('released', 'release'):
            initial_type = ResolveType.RELEASE
        else:
            initial_type = ResolveType.RELEASE if not assignment.is_active else ResolveType.ASSIGN
        form = ResolveRequestForm(initial={'request_type': initial_type})
    context = {
        'page_title': 'Request Resolve',
        'form': form,
        'assignment': assignment,
        'student': _student_record(assignment.student_id),
    }
    return render(request, 'allocations/resolve_form.html', context)


@login_required
def resolve_request_list(request):
    visible_halls = request.user.visible_halls()
    qs = ResolveRequest.objects.select_related('hall', 'seat__room', 'requested_by', 'resolved_by', 'assignment__seat__hall').order_by('-requested_at')
    # Hall managers see only their hall's requests + their own; admins see all
    if not request.user.is_app_admin:
        qs = qs.filter(Q(hall__in=visible_halls) | Q(seat__hall__in=visible_halls) | Q(requested_by=request.user)).distinct()
    # Filters
    status_f = (request.GET.get('status') or '').strip()
    q = (request.GET.get('q') or '').strip()
    if status_f in (ResolveStatus.PENDING, ResolveStatus.RESOLVED, ResolveStatus.REJECTED):
        qs = qs.filter(status=status_f)
    if q:
        qs = qs.filter(Q(student_id__icontains=q) | Q(seat__seat_number__icontains=q) | Q(hall__name__icontains=q) | Q(reason__icontains=q))

    from adminpanel.pagination import CursorPaginator
    paginator = CursorPaginator(qs, page_size=20, order_field='pk', reverse=True)
    page = paginator.page(request.GET.get('cursor'))
    params = request.GET.copy()
    params.pop('cursor', None)
    qs_str = params.urlencode()
    querystring = f'{qs_str}&' if qs_str else ''
    context = {
        'page_title': 'Resolve Requests',
        'objects': page.object_list,
        'page_obj': page,
        'querystring': querystring,
        'q': q,
        'status': status_f,
        'status_choices': ResolveStatus.choices,
    }
    return render(request, 'allocations/resolve_list.html', context)


@login_required
def resolve_request_detail(request, pk):
    qs = ResolveRequest.objects.select_related('hall', 'seat__room__floor__block', 'requested_by', 'resolved_by', 'assignment__seat__hall')
    # Manager can view only their hall's or their own; admin can view all
    if not request.user.is_app_admin:
        qs = qs.filter(Q(hall__in=request.user.visible_halls()) | Q(seat__hall__in=request.user.visible_halls()) | Q(requested_by=request.user))
    obj = get_object_or_404(qs, pk=pk)
    context = {
        'page_title': f'Resolve #{obj.pk} - {obj.get_status_display()}',
        'obj': obj,
        'can_resolve': request.user.is_app_admin and obj.status == ResolveStatus.PENDING,
    }
    return render(request, 'allocations/resolve_detail.html', context)


@login_required
def resolve_request_approve(request, pk):
    if not request.user.is_app_admin:
        messages.error(request, 'Only administrators can resolve requests.')
        return redirect('allocations:resolve_list')
    obj = get_object_or_404(ResolveRequest, pk=pk, status=ResolveStatus.PENDING)
    if request.method != 'POST':
        return redirect('allocations:resolve_detail', pk=pk)
    note = (request.POST.get('resolution_note') or '').strip()
    try:
        approve_resolve_request(obj, request.user, resolution_note=note)
        messages.success(request, f'Resolve request #{obj.pk} approved — assignment and associated slips deleted. Audit log retained.')
    except ValidationError as e:
        messages.error(request, str(e))
    return redirect('allocations:resolve_list')


@login_required
def resolve_request_reject(request, pk):
    if not request.user.is_app_admin:
        messages.error(request, 'Only administrators can reject requests.')
        return redirect('allocations:resolve_list')
    obj = get_object_or_404(ResolveRequest, pk=pk, status=ResolveStatus.PENDING)
    if request.method != 'POST':
        return redirect('allocations:resolve_detail', pk=pk)
    note = (request.POST.get('resolution_note') or '').strip()
    try:
        reject_resolve_request(obj, request.user, resolution_note=note)
        messages.success(request, f'Resolve request #{obj.pk} rejected — row unlocked.')
    except ValidationError as e:
        messages.error(request, str(e))
    return redirect('allocations:resolve_list')
