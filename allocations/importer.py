"""CSV importer for merit-list hall allocations.

Expected header row (order-insensitive, BOM tolerated):

    call_id,hall_code,student_id
    202601,HALALA,2101CSE001

Import rules:
- One single ``call_id`` per file; format ``YYYYNN`` (e.g. 202601).
- Every ``hall_code`` must exist in the halls table; a hall manager may only
- import rows whose code matches the hall they manage.
- One row per student within the file.
- A ``student_id`` must be unique within each call: if the same student
- appears twice in the same call, the import is rejected. The same student
- may appear in different calls.
- Activation policy: the FIRST-ever import is activated automatically (nothing
- to compare against). Any later import stays INACTIVE on purpose — activating
- it is a deliberate admin decision ("Set Active"), so a wrong file can never
- silently become the assignment source.
"""

import csv
import io

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from halls.models import Hall

from .models import AllocationCall, HallAllocation

try:
    from django.db import IntegrityError
except ImportError:
    IntegrityError = Exception

REQUIRED_HEADERS = ['call_id', 'hall_code', 'student_id']


def _rows(fileobj):
    """Decode + parse the uploaded file into stripped dict rows."""
    content = fileobj.read()
    if isinstance(content, bytes):
        try:
            content = content.decode('utf-8-sig')
        except UnicodeDecodeError as exc:
            raise ValidationError('The file is not valid UTF-8 text. Please upload a plain CSV file.') from exc
    reader = csv.DictReader(io.StringIO(content))
    headers = [(h or '').strip().lower() for h in (reader.fieldnames or [])]
    missing = [col for col in REQUIRED_HEADERS if col not in headers]
    if missing:
        raise ValidationError(
            f'Missing required column(s): {", ".join(missing)}. '
            f'Expected header: {", ".join(REQUIRED_HEADERS)}.'
        )
    return reader


def import_allocations(fileobj, acting_user=None):
    """Validate and import an allocation CSV. Returns a summary dict.

    Raises ``ValidationError`` whose messages list every problem found when
    nothing can be imported (all-or-nothing).
    """
    errors = []
    parsed = []
    seen_students = {}

    for line_no, raw in enumerate(_rows(fileobj), start=2):
        row = {(k or '').strip().lower(): (v or '').strip() for k, v in raw.items()}
        call_id = row.get('call_id', '')
        hall_code = row.get('hall_code', '').upper()
        student_id = row.get('student_id', '')

        try:
            year, sequence = AllocationCall.parse_call_id(call_id)
        except ValueError as exc:
            errors.append(f'Row {line_no}: {exc}')
            continue

        if not student_id:
            errors.append(f'Row {line_no}: student_id is required.')
            continue
        if len(student_id) > 10:
            errors.append(f'Row {line_no}: student_id "{student_id}" exceeds 10 characters.')
            continue
        if student_id in seen_students:
            errors.append(f'Row {line_no}: duplicate student {student_id} '
                          f'(already on row {seen_students[student_id]}).')
            continue
        seen_students[student_id] = line_no

        if not hall_code:
            errors.append(f'Row {line_no}: hall_code is required.')
            continue

        parsed.append({'call_id': call_id, 'year': year, 'sequence': sequence,
                       'hall_code': hall_code, 'student_id': student_id})

    if not parsed and not errors:
        raise ValidationError('The file contains no data rows.')

    # One call id per file.
    call_ids = {row['call_id'] for row in parsed}
    if len(call_ids) > 1:
        errors.append('All rows must use the same call_id — found: '
                      + ', '.join(sorted(call_ids)) + '.')
        raise ValidationError(errors)

    # Hall codes must exist; managers are limited to their own hall's code.
    allowed_codes = None
    if acting_user is not None and not acting_user.is_superuser:
        allowed_codes = set(acting_user.visible_halls().exclude(code__isnull=True)
                            .values_list('code', flat=True))
    hall_codes = {row['hall_code'] for row in parsed}
    known_codes = set(Hall.objects.filter(code__in=hall_codes).values_list('code', flat=True))
    for row in parsed:
        code = row['hall_code']
        if code not in known_codes:
            errors.append(f'Row {seen_students[row["student_id"]]}: no hall exists with code "{code}".')
        elif allowed_codes is not None and code not in allowed_codes:
            hall_name = Hall.objects.filter(code=code).first()
            label = f'{hall_name.name} ({code})' if hall_name else code
            errors.append(f'Row {seen_students[row["student_id"]]}: you manage a different hall — '
                          f'"{label}" cannot be imported by you.')

    if errors:
        raise ValidationError(errors)

    summary = {'call_id': call_ids.pop(), 'created': 0, 'updated': 0}
    with transaction.atomic():
        first = parsed[0]
        first_ever = not AllocationCall.objects.exists()
        call, created = AllocationCall.objects.get_or_create(
            call_id=first['call_id'],
            defaults={
                'year': first['year'],
                'sequence': first['sequence'],
                'is_active': False,
                'imported_by': acting_user,
                'imported_at': timezone.now(),
            },
        )
        summary['reused'] = not created

        if first_ever:
            # Seed case: the very first import becomes the active call so the
            # system is usable immediately. Every later import is left inactive
            # on purpose — activation is an explicit admin decision.
            AllocationCall.objects.exclude(pk=call.pk).filter(is_active=True).update(is_active=False)
            if not call.is_active:
                call.is_active = True
                call.imported_by = acting_user or call.imported_by
                call.save(update_fields=['is_active', 'imported_by'])
        summary['auto_activated'] = first_ever

        existing = {
            a.student_id: a
            for a in HallAllocation.objects.filter(call=call, student_id__in=[r['student_id'] for r in parsed])
        }
        to_create = []
        for row in parsed:
            allotment = existing.get(row['student_id'])
            if allotment is None:
                to_create.append(HallAllocation(
                    call=call,
                    hall_code=row['hall_code'],
                    student_id=row['student_id'],
                ))
                summary['created'] += 1
            elif allotment.hall_code != row['hall_code']:
                allotment.hall_code = row['hall_code']
                allotment.save(update_fields=['hall_code'])
                summary['updated'] += 1
        HallAllocation.objects.bulk_create(to_create)

    summary['total'] = len(parsed)
    summary['active_call'] = AllocationCall.active()
    return summary
