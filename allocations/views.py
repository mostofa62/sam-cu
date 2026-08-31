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

from .forms import AssignForm, ImportAllocationsForm, RevokeForm
from .importer import import_allocations
from .models import (AllocationCall, HallAllocation, OrderChoices, SeatAssignment,
                     SeatAssignmentLog, SeatMaintenance, SeatReleaseReason)
from .services import assign_seat, revoke_seat, validate_seat_assignable


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

    allotment_rows = []
    if selected is not None:
        allotment_rows = list(
            HallAllocation.objects
            .filter(call=selected, hall_code__in=visible_codes)
            .select_related('call')
            .order_by('student_id')
        )
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

        # CSV export includes subject details
        if request.GET.get('export') == 'csv':
            import csv
            from django.http import HttpResponse
            resp = HttpResponse(content_type='text/csv')
            resp['Content-Disposition'] = f'attachment; filename="allotments_{selected.call_id}.csv"'
            w = csv.writer(resp)
            w.writerow(['student_id', 'student_name', 'subject_code', 'subject', 'hall_code', 'call_id'])
            for a in allotment_rows:
                w.writerow([a.student_id, a.student_name or '', a.subject_code or '', a.subject or '', a.hall_code, selected.call_id])
            return resp

    context = {
        'page_title': 'Hall Allotments',
        'calls': calls,
        'selected_call': selected,
        'allotments': allotment_rows,
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
