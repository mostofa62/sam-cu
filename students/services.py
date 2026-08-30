"""Bridge to the external student information system.

``pull_students_from_external_system`` is the single integration point the
admin panel's “Pull students” button uses. It upserts master student rows by
their natural ``student_id`` key: existing rows are refreshed, unknown IDs are
inserted. Until a real feed (API / dump) is configured the demo source below
reuses the bundled sample dataset, so the flow can be exercised end to end.
"""
from django.db import transaction

from .models import Student

# Fields the external system owns — pulled values overwrite local edits for
# these columns only; everything else stays untouched.
PULL_FIELDS = (
    'session', 'entity_id', 'subject_id', 'name_en', 'name_bn', 'gender',
    'religion', 'dob_ymd', 'bloodgroup', 'nationality', 'nid', 'phone',
    'fname_en', 'fphone', 'mname_en', 'mphone',
    'perm_addr', 'perm_dist', 'pres_addr', 'pres_dist',
    'hall_code', 'student_status', 'adm_quota',
)


def _demo_source_rows():
    """Sample payload standing in for the real external-system response."""
    from students.management.commands.seed_students import STUDENTS
    return STUDENTS


@transaction.atomic
def pull_students_from_external_system(source=None):
    """Upsert students from ``source`` (defaults to the demo payload).

    Returns ``(created_count, updated_count)``.
    """
    created = updated = 0
    for row in (source if source is not None else _demo_source_rows()):
        student_id = row.get('student_id')
        if not student_id:
            continue
        student, was_created = Student.objects.get_or_create(student_id=student_id)
        changed = False
        for field in PULL_FIELDS:
            value = row.get(field)
            if value is not None and getattr(student, field, None) != value:
                setattr(student, field, value)
                changed = True
        if was_created:
            # A brand-new row keeps every supplied field, even nullable ones.
            for field, value in row.items():
                if hasattr(student, field):
                    setattr(student, field, value)
            student.save()
            created += 1
        elif changed:
            student.save()
            updated += 1
    return created, updated
