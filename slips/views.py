from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from allocations.models import SeatAssignment, SeatAssignmentLog
from halls.models import Hall, Seat
from students.models import Student

from .forms import SlipForm, get_default_items_data, parse_slip_items
from .models import DEFAULT_SLIP_LABELS, Slip, SlipItem, SlipType, amount_to_words


@login_required
def slip_list(request):
    visible_halls = request.user.visible_halls()
    qs = Slip.objects.filter(hall__in=visible_halls).select_related('hall', 'seat__room', 'issued_by').order_by('-issued_at', '-id')
    # filters
    q = (request.GET.get('q') or '').strip()
    slip_type = (request.GET.get('type') or '').strip()
    hall_id = (request.GET.get('hall') or '').strip()
    if q:
        qs = qs.filter(Q(serial_number__icontains=q) | Q(student_id__icontains=q) | Q(student_name__icontains=q))
    if slip_type in (SlipType.ASSIGN, SlipType.RELEASE):
        qs = qs.filter(slip_type=slip_type)
    if hall_id and hall_id.isdigit():
        qs = qs.filter(hall_id=int(hall_id))
    context = {
        'page_title': 'Hall Slips / Invoices',
        'slips': qs[:200],
        'q': q,
        'selected_type': slip_type,
        'selected_hall': hall_id,
        'halls': visible_halls,
    }
    return render(request, 'slips/list.html', context)


@login_required
def slip_detail(request, pk):
    slip = get_object_or_404(Slip.objects.select_related('hall', 'seat__room__floor', 'issued_by'), pk=pk, hall__in=request.user.visible_halls())
    items = slip.items.all().order_by('sort_order', 'id')
    is_released = False
    if slip.slip_type == SlipType.ASSIGN and slip.student_id:
        is_released = SeatAssignment.objects.filter(
            student_id=slip.student_id, released_at__isnull=False
        ).exists()
    context = {
        'page_title': f'Slip {slip.serial_number}',
        'slip': slip,
        'items': items,
        'is_released': is_released,
    }
    return render(request, 'slips/detail.html', context)


@login_required
def slip_print(request, pk):
    slip = get_object_or_404(Slip.objects.select_related('hall', 'seat__room__floor__block', 'seat__hall', 'issued_by'), pk=pk, hall__in=request.user.visible_halls())
    items = list(slip.items.all().order_by('sort_order', 'id'))
    # Ensure total consistent
    total = sum((i.amount for i in items), Decimal('0.00'))
    context = {
        'page_title': f'Print {slip.serial_number}',
        'slip': slip,
        'items': items,
        'total': total,
        'total_in_words': slip.total_in_words or amount_to_words(total),
        'now': timezone.localtime(timezone.now()),
    }
    return render(request, 'slips/print.html', context)



def _prefill_from_student(student_id):
    stu = Student.objects.filter(student_id=student_id).first()
    if not stu:
        return {}
    return {
        'student_name': stu.name_en or stu.name_bn or '',
        'student_name_bn': stu.name_bn or '',
        'father_name': stu.fname_en or stu.fname_bn or '',
        'father_name_bn': stu.fname_bn or '',
        'subject': stu.subject or '',
        'subject_code': stu.subject_code or '',
    }


def _previous_assign_items(student_id, visible_halls=None):
    """Return (slip, items_data) for latest assign slip of student, filtered to visible halls."""
    qs = Slip.objects.filter(student_id=student_id, slip_type=SlipType.ASSIGN)
    if visible_halls is not None:
        qs = qs.filter(hall__in=visible_halls)
    slip = qs.order_by('-event_date', '-issued_at', '-id').first()
    if not slip:
        return None, None
    items = list(slip.items.order_by('sort_order', 'id').values_list('label', 'amount'))
    items_data = [(lbl, amt) for lbl, amt in items] if items else None
    return slip, items_data


def _can_create_release(student_id, visible_halls):
    """Validate release slip can be created.

    Rules:
    - Student must have been released (released_at present) → allow multiple release slips.
    - Student with active assignment → block (must release first).
    - Active seat in another hall → block.
    - No assignment at all → block.
    """
    latest = SeatAssignment.objects.filter(student_id=student_id, seat__hall__in=visible_halls).order_by('-released_at', '-assigned_at').first()
    if latest and latest.released_at:
        return True, "", latest
    active = SeatAssignment.objects.filter(student_id=student_id, is_active=True, seat__hall__in=visible_halls).select_related('seat__hall').first()
    if active:
        return False, f"Student {student_id} has not been released yet (still assigned to {active.seat.full_label} since {timezone.localtime(active.assigned_at).strftime('%d/%m/%Y %H:%M')}) — cannot create release slip. Please release the seat first.", active
    any_active_else = SeatAssignment.objects.filter(student_id=student_id, is_active=True).select_related('seat__hall').first()
    if any_active_else:
        return False, f"Student {student_id} has an active seat in {any_active_else.seat.hall.name} (another hall) — you cannot create a release slip.", any_active_else
    ps, _ = _previous_assign_items(student_id, visible_halls)
    if ps:
        if ps.assignment_id and ps.assignment and ps.assignment.released_at:
            return True, "", ps.assignment
        return False, f"Student {student_id} has no active assignment — already released.", ps.assignment if ps.assignment_id else None
    return False, f"No seat assignment found for {student_id} — cannot create release slip.", None


def _can_create_assign(student_id, visible_halls):
    """Validate assign slip can be created.

    Rules:
    - If student's latest assignment has released_at set → block (already released).
    - Otherwise → allow.
    """
    latest = SeatAssignment.objects.filter(student_id=student_id, seat__hall__in=visible_halls).order_by('-released_at', '-assigned_at').first()
    if latest and latest.released_at:
        return False, f"Student {student_id} has already been released — cannot create another assign slip.", latest
    return True, "", latest


@login_required
def student_lookup_json(request):
    """AJAX: given ?student_id=...&type=assign|release, return populated data + validation."""
    student_id = (request.GET.get('student_id') or '').strip()
    slip_type = (request.GET.get('type') or '').strip()
    if slip_type not in (SlipType.ASSIGN, SlipType.RELEASE):
        slip_type = ''
    if not student_id:
        return JsonResponse({'ok': False, 'error': 'Student ID required'}, status=400)
    visible_halls = request.user.visible_halls()
    # student master data
    stu = Student.objects.filter(student_id=student_id).first()
    student_data = {}
    if stu:
        student_data = {
            'student_name': stu.name_en or stu.name_bn or '',
            'student_name_bn': stu.name_bn or '',
            'father_name': stu.fname_en or stu.fname_bn or '',
            'father_name_bn': stu.fname_bn or '',
            'subject': stu.subject or '',
            'subject_code': stu.subject_code or '',
        }
    else:
        student_data = {'student_name': '', 'student_name_bn': '', 'father_name': '', 'father_name_bn': '', 'subject': '', 'subject_code': ''}

    # active assignment (visible halls only)
    active_qs = SeatAssignment.objects.filter(student_id=student_id, is_active=True).select_related('seat__hall', 'seat__room', 'seat__room__floor__block')
    # restrict to visible halls for validation
    active_in_hall = active_qs.filter(seat__hall__in=visible_halls).first()
    any_active = SeatAssignment.objects.filter(student_id=student_id, is_active=True).select_related('seat__hall').first()

    assignment_data = None
    has_assignment = active_in_hall is not None
    # For release, must have active assignment in visible hall
    can_create_release = has_assignment
    # For assign, slip is normally created after assignment, so also expects has_assignment; but allow creation even if not (maybe manual)
    # We'll just report has_assignment
    if active_in_hall:
        assignment_data = {
            'hall_id': active_in_hall.seat.hall_id,
            'hall_name': active_in_hall.seat.hall.name,
            'seat_id': active_in_hall.seat_id,
            'seat_label': active_in_hall.seat.seat_label,
            'full_label': active_in_hall.seat.full_label,
            'assigned_at': timezone.localtime(active_in_hall.assigned_at).isoformat(),
            'assigned_at_display': timezone.localtime(active_in_hall.assigned_at).strftime('%d/%m/%Y %H:%M'),
        }
    elif any_active:
        # exists but in other hall not visible
        assignment_data = {
            'hall_id': None,
            'hall_name': any_active.seat.hall.name,
            'other_hall': True,
        }

    # previous assign slip for release prefill
    prev_slip = None
    prev_items = None
    if slip_type == SlipType.RELEASE or True:  # always provide for release context, but also for assign we can provide
        ps, pi = _previous_assign_items(student_id, visible_halls)
        if ps:
            prev_slip = {
                'id': ps.pk,
                'serial_number': ps.serial_number,
                'hall_id': ps.hall_id,
                'hall_name': ps.hall_name_snapshot or (ps.hall.name if ps.hall_id else ''),
                'seat_id': ps.seat_id,
                'seat_label': ps.seat_label_snapshot,
                'event_date': timezone.localtime(ps.event_date).isoformat() if ps.event_date else None,
                'student_name': ps.student_name,
                'father_name': ps.father_name,
                'subject': ps.subject,
                'subject_code': ps.subject_code,
            }
            prev_items = [{'label': lbl, 'amount': str(amt)} for lbl, amt in (pi or [])]

    # validation messages — use helper for release to ensure not already released
    validation = {'can_create': True, 'message': '', 'level': 'ok'}
    if slip_type == SlipType.RELEASE:
        can_r, msg_r, _ = _can_create_release(student_id, visible_halls)
        if not can_r:
            validation = {'can_create': False, 'message': msg_r, 'level': 'error'}
        elif not prev_slip:
            validation = {'can_create': True, 'message': 'No previous assign slip found — defaults will be used (edit as needed).', 'level': 'warning'}
    elif slip_type == SlipType.ASSIGN:
        can_a, msg_a, _ = _can_create_assign(student_id, visible_halls)
        if not can_a:
            validation = {'can_create': False, 'message': msg_a, 'level': 'error'}
        elif any_active and not has_assignment:
            validation = {'can_create': True, 'message': f'Student already has an active seat in {any_active.seat.hall.name} (outside your hall).', 'level': 'warning'}
        elif not stu:
            validation = {'can_create': True, 'message': 'No master record found for this student ID — double-check.', 'level': 'warning'}

    return JsonResponse({
        'ok': True,
        'student_id': student_id,
        'slip_type': slip_type,
        'student': student_data,
        'student_found': stu is not None,
        'has_assignment': has_assignment,
        'assignment': assignment_data,
        'any_active_other_hall': any_active is not None and not has_assignment,
        'previous_assign_slip': prev_slip,
        'previous_assign_items': prev_items or [],
        'validation': validation,
    })


def _create_slip_with_items(form, items_data, user, assignment=None):
    """Save slip and its items atomically; recalc total."""
    with transaction.atomic():
        slip = form.save(commit=False)
        slip.issued_by = user
        if assignment is not None:
            slip.assignment = assignment
            if not slip.event_date or slip.event_date == slip.assignment.assigned_at:
                pass
        # Auto-populate remarks with release reason for release slips
        if slip.slip_type == SlipType.RELEASE and not slip.remarks:
            released_ass = assignment
            if not released_ass and slip.student_id:
                released_ass = SeatAssignment.objects.filter(
                    student_id=slip.student_id, released_at__isnull=False
                ).order_by('-released_at').first()
            if released_ass and released_ass.released_reason:
                slip.remarks = released_ass.released_reason.name
        # fill snapshots if not already
        if slip.hall_id and not slip.hall_name_snapshot:
            slip.hall_name_snapshot = slip.hall.name
        if slip.seat_id and not slip.seat_label_snapshot:
            try:
                slip.seat_label_snapshot = slip.seat.full_label
            except Exception:
                slip.seat_label_snapshot = slip.seat.seat_label
        # Leave signature blank for manual signing — no auto-fill
        slip.signature_name = ''
        slip.signature_title = ''
        # Auto-populate Bengali names from Student table
        if slip.student_id and (not slip.student_name_bn or not slip.father_name_bn):
            stu = Student.objects.filter(student_id=slip.student_id).first()
            if stu:
                if not slip.student_name_bn and stu.name_bn:
                    slip.student_name_bn = stu.name_bn
                if not slip.father_name_bn and stu.fname_bn:
                    slip.father_name_bn = stu.fname_bn
        # we want serial generated on save
        slip.total_amount = Decimal('0.00')
        slip.total_in_words = amount_to_words(Decimal('0.00'))
        # try save with retry on serial collision
        for _ in range(3):
            try:
                slip.save()
                break
            except IntegrityError:
                # regenerate
                from .models import generate_serial
                slip.serial_number = generate_serial(slip.slip_type)
        else:
            slip.save()
        # create items
        SlipItem.objects.filter(slip=slip).delete()
        total = Decimal('0.00')
        for idx, (label, amount) in enumerate(items_data):
            SlipItem.objects.create(slip=slip, label=label, amount=amount, sort_order=idx)
            total += amount
        slip.total_amount = total
        slip.total_in_words = amount_to_words(total)
        slip.save(update_fields=['total_amount', 'total_in_words', 'updated_at'])
    return slip


@login_required
def slip_create(request):
    visible_halls = request.user.visible_halls()
    initial = {}
    # Prefill from query params: student_id, assignment_id, log_id, type
    student_id_q = (request.GET.get('student_id') or '').strip()
    assignment_id = request.GET.get('assignment_id')
    slip_type_q = request.GET.get('type') if request.GET.get('type') in (SlipType.ASSIGN, SlipType.RELEASE) else ''
    linked_assignment = None
    preview_ass = None
    if student_id_q:
        initial['student_id'] = student_id_q
        initial.update(_prefill_from_student(student_id_q))
        # also try to guess hall/seat from active assignment
        ass = SeatAssignment.objects.filter(student_id=student_id_q, is_active=True).select_related('seat__hall').first()
        if ass and ass.seat.hall in visible_halls:
            initial['hall'] = ass.seat.hall
            initial['seat'] = ass.seat
            preview_ass = ass
    if assignment_id and assignment_id.isdigit():
        ass = get_object_or_404(SeatAssignment.objects.select_related('seat__hall', 'seat__room'), pk=int(assignment_id))
        if ass.seat.hall not in visible_halls and not request.user.is_app_admin:
            messages.error(request, 'You do not have access to that hall.')
            return redirect('slips:list')
        linked_assignment = ass
        preview_ass = ass
        initial['student_id'] = ass.student_id
        initial.update(_prefill_from_student(ass.student_id))
        initial['hall'] = ass.seat.hall
        initial['seat'] = ass.seat
        initial['slip_type'] = SlipType.ASSIGN
        slip_type_q = SlipType.ASSIGN
    if slip_type_q:
        initial['slip_type'] = slip_type_q

    # Determine items initial — for release, prefill from previous assign slip
    default_items = get_default_items_data()
    release_prefill_items = None
    release_prev_slip = None
    # Detect release intent: explicit type=release or student_id_q with no active assignment implies release
    is_release = (initial.get('slip_type') == SlipType.RELEASE or slip_type_q == SlipType.RELEASE)
    if is_release and student_id_q:
        # Use latest assign slip for this student in visible halls
        prev_slip, prev_items = _previous_assign_items(student_id_q, visible_halls)
        if prev_slip and prev_items:
            release_prev_slip = prev_slip
            release_prefill_items = prev_items
            # Backfill hall/seat/student details from previous assign if not already guessed
            if 'hall' not in initial:
                initial['hall'] = prev_slip.hall
            if 'seat' not in initial and prev_slip.seat_id:
                initial['seat'] = prev_slip.seat
            for k in ['student_name', 'father_name', 'subject', 'subject_code']:
                if not initial.get(k) and getattr(prev_slip, k, ''):
                    initial[k] = getattr(prev_slip, k)
            if not preview_ass and prev_slip.assignment_id:
                # For date preview, keep assignment reference if slip has it
                try:
                    preview_ass = prev_slip.assignment
                except Exception:
                    pass

    if request.method == 'POST':
        # Server-side auto-populate for direct student_id entry (no AJAX)
        # For release, if hall/seat missing and student has assignment, fill from assignment/previous slip
        _post = request.POST.copy()
        _tmp_type = (_post.get('slip_type') or '').strip()
        _tmp_sid = (_post.get('student_id') or '').strip()
        _is_rel = _tmp_type == SlipType.RELEASE
        _is_asn = _tmp_type == SlipType.ASSIGN
        if _tmp_sid:
            # Auto-fill hall/seat if missing (for both assign & release) from assignment/previous slip
            if not _post.get('hall'):
                ass = SeatAssignment.objects.filter(student_id=_tmp_sid, seat__hall__in=visible_halls).order_by('-is_active', '-released_at', '-assigned_at').first()
                if ass:
                    _post['hall'] = str(ass.seat.hall_id)
                    if not _post.get('seat'):
                        _post['seat'] = str(ass.seat_id)
                    if linked_assignment is None:
                        linked_assignment = ass
                else:
                    ps, _ = _previous_assign_items(_tmp_sid, visible_halls)
                    if ps:
                        _post['hall'] = str(ps.hall_id)
                        if not _post.get('seat') and ps.seat_id:
                            _post['seat'] = str(ps.seat_id)
                        if linked_assignment is None and ps.assignment_id:
                            try:
                                linked_assignment = SeatAssignment.objects.get(pk=ps.assignment_id)
                            except Exception:
                                pass
            elif not _post.get('seat'):
                hall_id = _post.get('hall')
                ass2 = SeatAssignment.objects.filter(student_id=_tmp_sid, seat__hall_id=hall_id).order_by('-is_active', '-released_at', '-assigned_at').first()
                if ass2:
                    _post['seat'] = str(ass2.seat_id)
                    if linked_assignment is None:
                        linked_assignment = ass2
            # Auto-fill student info from master or previous slip if empty (for both)
            _stu_pref = _prefill_from_student(_tmp_sid)
            for _fld in ['student_name', 'father_name', 'subject', 'subject_code']:
                if not _post.get(_fld) and _stu_pref.get(_fld):
                    _post[_fld] = _stu_pref[_fld]
            if not _post.get('student_name') or not _post.get('father_name') or not _post.get('subject'):
                _ps_tmp, _ = _previous_assign_items(_tmp_sid, visible_halls)
                if _ps_tmp:
                    if not _post.get('student_name') and _ps_tmp.student_name:
                        _post['student_name'] = _ps_tmp.student_name
                    if not _post.get('father_name') and _ps_tmp.father_name:
                        _post['father_name'] = _ps_tmp.father_name
                    if not _post.get('subject') and _ps_tmp.subject:
                        _post['subject'] = _ps_tmp.subject
                    if not _post.get('subject_code') and _ps_tmp.subject_code:
                        _post['subject_code'] = _ps_tmp.subject_code
        # Preserve linked assignment from POST hidden or GET param (overrides auto)
        post_assignment_id = _post.get('assignment_id') or assignment_id
        if post_assignment_id and str(post_assignment_id).isdigit():
            try:
                linked_assignment = SeatAssignment.objects.get(pk=int(post_assignment_id))
            except SeatAssignment.DoesNotExist:
                pass
        form = SlipForm(_post, user=request.user)
        items_data = parse_slip_items(_post)
        # For release, if user left fee rows as defaults (all 0), use previous assign slip's items
        if _is_rel and _tmp_sid and (not items_data or all(amt == 0 or amt == Decimal('0.00') for _, amt in items_data)):
            _ps2, _pi2 = _previous_assign_items(_tmp_sid, visible_halls)
            if _ps2 and _pi2:
                items_data = _pi2
        # Validate release must have active assignment not yet released
        if _is_rel and _tmp_sid:
            can, msg, _ = _can_create_release(_tmp_sid, visible_halls)
            if not can:
                form.add_error('student_id', msg)
        # Validate assign: cannot create if student already released
        if _is_asn and _tmp_sid:
            can_a, msg_a, _ = _can_create_assign(_tmp_sid, visible_halls)
            if not can_a:
                form.add_error('student_id', msg_a)
        # if no items submitted, fallback to defaults (with posted amounts if any)
        if not items_data:
            # try to reconstruct from default fields? but parse already empty means no rows
            items_data = []
        if form.is_valid():
            # at least one item? if empty, create defaults zero
            if not items_data:
                items_data = default_items
            try:
                slip = _create_slip_with_items(form, items_data, request.user, assignment=linked_assignment)
            except ValidationError as e:
                messages.error(request, str(e))
            else:
                messages.success(request, f'Slip {slip.serial_number} created.')
                return redirect('slips:detail', pk=slip.pk)
        # on invalid, keep items_data for re-render
    else:
        if 'release_prefill_items' in locals() and release_prefill_items is not None:
            items_data = release_prefill_items
        else:
            items_data = default_items
        form = SlipForm(initial=initial, user=request.user)

    # Build preview for the auto-derived date banner
    assignment_date_preview = None
    assignment_date_label = None
    src = linked_assignment or preview_ass
    if src:
        if src.released_at and (initial.get('slip_type') == SlipType.RELEASE or slip_type_q == SlipType.RELEASE):
            assignment_date_preview = src.released_at
            assignment_date_label = 'released_at from allocations_seatassignment'
        else:
            assignment_date_preview = src.assigned_at
            assignment_date_label = 'assigned_at from allocations_seatassignment'
    context = {
        'page_title': 'Create Hall Slip',
        'form': form,
        'items_data': items_data,  # list of (label, amount)
        'is_edit': False,
        'assignment_id': assignment_id,
        'assignment_date_preview': assignment_date_preview,
        'assignment_date_label': assignment_date_label,
    }
    return render(request, 'slips/form.html', context)


@login_required
def slip_edit(request, pk):
    slip = get_object_or_404(Slip, pk=pk, hall__in=request.user.visible_halls())
    if slip.slip_type == SlipType.ASSIGN and slip.student_id:
        if SeatAssignment.objects.filter(student_id=slip.student_id, released_at__isnull=False).exists():
            messages.error(request, f'Cannot edit {slip.serial_number} — student {slip.student_id} already released.')
            return redirect('slips:detail', pk=slip.pk)
    existing_items = list(slip.items.all().order_by('sort_order', 'id').values_list('label', 'amount'))
    # convert to list of tuples
    existing_items = [(lbl, amt) for lbl, amt in existing_items]
    if not existing_items:
        existing_items = get_default_items_data()

    if request.method == 'POST':
        form = SlipForm(request.POST, instance=slip, user=request.user)
        items_data = parse_slip_items(request.POST)
        if form.is_valid():
            if not items_data:
                items_data = get_default_items_data()
            try:
                slip = _create_slip_with_items(form, items_data, slip.issued_by or request.user)
                # keep original serial / issued_at ?
            except ValidationError as e:
                messages.error(request, str(e))
            else:
                messages.success(request, f'Slip {slip.serial_number} updated.')
                return redirect('slips:detail', pk=slip.pk)
        # keep items_data for error case
    else:
        form = SlipForm(instance=slip, user=request.user)
        items_data = existing_items

    context = {
        'page_title': f'Edit Slip {slip.serial_number}',
        'form': form,
        'items_data': items_data,
        'is_edit': True,
        'slip': slip,
        'assignment_date_preview': slip.event_date,
        'assignment_date_label': ('released_at' if slip.slip_type == SlipType.RELEASE else 'assigned_at') + ' (stored snapshot from allocations_seatassignment)',
    }
    return render(request, 'slips/form.html', context)


@login_required
def slip_delete(request, pk):
    slip = get_object_or_404(Slip, pk=pk, hall__in=request.user.visible_halls())
    if slip.slip_type == SlipType.ASSIGN and slip.student_id:
        if SeatAssignment.objects.filter(student_id=slip.student_id, released_at__isnull=False).exists():
            messages.error(request, f'Cannot delete {slip.serial_number} — student {slip.student_id} already released.')
            return redirect('slips:detail', pk=slip.pk)
    if request.method == 'POST':
        serial = slip.serial_number
        slip.delete()
        messages.success(request, f'Slip {serial} deleted.')
        return redirect('slips:list')
    context = {
        'page_title': f'Delete Slip {slip.serial_number}',
        'slip': slip,
    }
    return render(request, 'slips/delete_confirm.html', context)


# Convenience shortcuts from assignment/release logs

@login_required
def slip_create_from_assignment(request, pk):
    """Shortcut: /slips/from-assignment/<pk>/ creates assign slip prefilled."""
    ass = get_object_or_404(SeatAssignment.objects.select_related('seat__hall', 'seat__room__floor'), pk=pk, is_active=True)
    if ass.seat.hall not in request.user.visible_halls() and not request.user.is_app_admin:
        messages.error(request, 'You do not have access to that hall.')
        return redirect('slips:list')
    # redirect to create with query params to reuse logic; or directly render form
    return redirect(f"/slips/create/?assignment_id={ass.pk}&type=assign")


@login_required
def slip_create_for_release(request):
    """Expect ?student_id=...&seat_id=... ; creates release slip prefilled."""
    student_id = (request.GET.get('student_id') or request.POST.get('student_id') or '').strip()
    # also support POST create directly?
    if request.method == 'POST':
        # Server-side auto-populate for direct student_id entry (no AJAX)
        _post = request.POST.copy()
        _tmp_sid2 = (_post.get('student_id') or '').strip()
        visible_halls2 = request.user.visible_halls()
        if _tmp_sid2:
            _has_any2 = SeatAssignment.objects.filter(student_id=_tmp_sid2, seat__hall__in=visible_halls2).exists() or Slip.objects.filter(student_id=_tmp_sid2, hall__in=visible_halls2, slip_type=SlipType.ASSIGN).exists()
            if not _has_any2:
                # Will add form error after form creation
                pass
            else:
                if not _post.get('hall'):
                    ass2 = SeatAssignment.objects.filter(student_id=_tmp_sid2, seat__hall__in=visible_halls2).order_by('-is_active', '-released_at', '-assigned_at').first()
                    if ass2:
                        _post['hall'] = str(ass2.seat.hall_id)
                        if not _post.get('seat'):
                            _post['seat'] = str(ass2.seat_id)
                    else:
                        ps2, _ = _previous_assign_items(_tmp_sid2, visible_halls2)
                        if ps2:
                            _post['hall'] = str(ps2.hall_id)
                            if not _post.get('seat') and ps2.seat_id:
                                _post['seat'] = str(ps2.seat_id)
                elif not _post.get('seat'):
                    hall_id2 = _post.get('hall')
                    ass3 = SeatAssignment.objects.filter(student_id=_tmp_sid2, seat__hall_id=hall_id2).order_by('-is_active', '-released_at', '-assigned_at').first()
                    if ass3:
                        _post['seat'] = str(ass3.seat_id)
                # Auto-fill student info if empty
                if _tmp_sid2:
                    _stu2 = _prefill_from_student(_tmp_sid2)
                    for _fld2 in ['student_name', 'father_name', 'subject', 'subject_code']:
                        if not _post.get(_fld2) and _stu2.get(_fld2):
                            _post[_fld2] = _stu2[_fld2]
                    if not _post.get('student_name') or not _post.get('father_name') or not _post.get('subject'):
                        _ps_tmp2, _ = _previous_assign_items(_tmp_sid2, visible_halls2)
                        if _ps_tmp2:
                            if not _post.get('student_name') and _ps_tmp2.student_name:
                                _post['student_name'] = _ps_tmp2.student_name
                            if not _post.get('father_name') and _ps_tmp2.father_name:
                                _post['father_name'] = _ps_tmp2.father_name
                            if not _post.get('subject') and _ps_tmp2.subject:
                                _post['subject'] = _ps_tmp2.subject
                            if not _post.get('subject_code') and _ps_tmp2.subject_code:
                                _post['subject_code'] = _ps_tmp2.subject_code
        # handle as normal create but force type release
        form = SlipForm(_post, user=request.user)
        # force slip_type to release if not set (ensure form has it)
        if not _post.get('slip_type'):
            _post['slip_type'] = SlipType.RELEASE
            form = SlipForm(_post, user=request.user)
        items_data = parse_slip_items(_post)
        # For release, if fee rows left as defaults, use previous assign items
        if _tmp_sid2 and (not items_data or all(amt == 0 or amt == Decimal('0.00') for _, amt in items_data)):
            _ps3, _pi3 = _previous_assign_items(_tmp_sid2, visible_halls2)
            if _ps3 and _pi3:
                items_data = _pi3
        # Validate release must have active assignment not yet released
        if _tmp_sid2:
            can2, msg2, _ = _can_create_release(_tmp_sid2, visible_halls2)
            if not can2:
                form.add_error('student_id', msg2)
        if form.is_valid():
            # ensure type
            with transaction.atomic():
                slip = form.save(commit=False)
                slip.slip_type = SlipType.RELEASE
                slip.issued_by = request.user
                # Leave signature blank for manual signing
                slip.signature_name = ''
                slip.signature_title = ''
                # Auto-populate remarks with release reason
                if not slip.remarks and _tmp_sid2:
                    released_ass2 = SeatAssignment.objects.filter(
                        student_id=_tmp_sid2, released_at__isnull=False
                    ).order_by('-released_at').first()
                    if released_ass2 and released_ass2.released_reason:
                        slip.remarks = released_ass2.released_reason.name
                # Auto-populate Bengali names from Student table
                if _tmp_sid2 and (not slip.student_name_bn or not slip.father_name_bn):
                    stu2 = Student.objects.filter(student_id=_tmp_sid2).first()
                    if stu2:
                        if not slip.student_name_bn and stu2.name_bn:
                            slip.student_name_bn = stu2.name_bn
                        if not slip.father_name_bn and stu2.fname_bn:
                            slip.father_name_bn = stu2.fname_bn
                slip.save()
                # items
                if not items_data:
                    items_data = get_default_items_data()
                total = Decimal('0.00')
                for idx, (lbl, amt) in enumerate(items_data):
                    SlipItem.objects.create(slip=slip, label=lbl, amount=amt, sort_order=idx)
                    total += amt
                slip.total_amount = total
                slip.total_in_words = amount_to_words(total)
                slip.save(update_fields=['total_amount', 'total_in_words'])
            messages.success(request, f'Release slip {slip.serial_number} created.')
            return redirect('slips:detail', pk=slip.pk)
        context = {'page_title': 'Create Release Slip', 'form': form, 'items_data': items_data, 'is_edit': False}
        return render(request, 'slips/form.html', context)

    # GET: show prefilled form
    preview_ass = None
    initial = {'slip_type': SlipType.RELEASE}
    # Try previous assign slip for this student (to copy fee items)
    prev_slip = None
    prev_items = None
    if student_id:
        initial['student_id'] = student_id
        initial.update(_prefill_from_student(student_id))
        # try to get last assignment (even inactive) for seat/hall
        ass = SeatAssignment.objects.filter(student_id=student_id).select_related('seat__hall').order_by('-assigned_at').first()
        if ass and ass.seat.hall in request.user.visible_halls():
            initial['hall'] = ass.seat.hall
            initial['seat'] = ass.seat
            preview_ass = ass
        # Also try previous assign slip for fee items and hall/seat fallback
        ps, pi = _previous_assign_items(student_id, request.user.visible_halls())
        if ps and pi:
            prev_slip = ps
            prev_items = pi
            if 'hall' not in initial:
                initial['hall'] = ps.hall
            if 'seat' not in initial and ps.seat_id:
                initial['seat'] = ps.seat
            for k in ['student_name', 'father_name', 'subject', 'subject_code']:
                if not initial.get(k) and getattr(ps, k, ''):
                    initial[k] = getattr(ps, k)
    form = SlipForm(initial=initial, user=request.user)
    # ensure release type locked?
    form.fields['slip_type'].initial = SlipType.RELEASE
    assignment_date_preview = None
    assignment_date_label = None
    if preview_ass:
        assignment_date_preview = preview_ass.released_at or preview_ass.assigned_at
        assignment_date_label = 'released_at' if preview_ass.released_at else 'assigned_at'
        assignment_date_label += ' from allocations_seatassignment'
    elif prev_slip:
        assignment_date_preview = prev_slip.event_date
        assignment_date_label = 'event_date from previous assign slip'
    # Use previous assign fee items for release, allow user to reduce
    items_data = prev_items if prev_items is not None else get_default_items_data()
    context = {
        'page_title': 'Create Release Slip',
        'form': form,
        'items_data': items_data,
        'is_edit': False,
        'assignment_date_preview': assignment_date_preview,
        'assignment_date_label': assignment_date_label,
    }
    return render(request, 'slips/form.html', context)
