# Squashed initial — generated from 0001_initial + 0002_... + 0004_... + 0005_... + 0006_... + 0007_... (2026-09-01)
# Seed data migration 0003_seed_release_reasons removed — use `python manage.py seed_reasons` instead.
# Represents final state of allocations models.

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('halls', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # SeatReleaseReason (from 0002)
        migrations.CreateModel(
            name='SeatReleaseReason',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text='Reason shown in the release dropdown.', max_length=255, unique=True)),
                ('is_active', models.BooleanField(db_index=True, default=True)),
                ('sort_order', models.PositiveSmallIntegerField(default=0)),
            ],
            options={
                'verbose_name': 'Seat Release Reason',
                'verbose_name_plural': 'Seat Release Reasons',
                'ordering': ['sort_order', 'id'],
            },
        ),
        # SeatAssignmentLog (from 0001 + 0002 release_reason)
        migrations.CreateModel(
            name='SeatAssignmentLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('student_id', models.CharField(db_index=True, max_length=50)),
                ('order', models.PositiveSmallIntegerField(choices=[(1, 'Primary'), (2, 'Secondary')], default=1)),
                ('action', models.CharField(choices=[('assigned', 'Assigned'), ('released', 'Released')], db_index=True, max_length=10)),
                ('note', models.CharField(blank=True, max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('performed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='assignment_logs', to=settings.AUTH_USER_MODEL)),
                ('release_reason', models.ForeignKey(blank=True, help_text='Reason selected when a seat was released.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='logs', to='allocations.seatreleasereason')),
                ('seat', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='assignment_logs', to='halls.seat')),
            ],
            options={
                'verbose_name': 'Seat Assignment Log',
                'verbose_name_plural': 'Seat Assignment Logs',
                'ordering': ['-created_at'],
            },
        ),
        # SeatMaintenance (unchanged from 0001)
        migrations.CreateModel(
            name='SeatMaintenance',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('reason', models.CharField(help_text='Reason for blocking the seat.', max_length=255)),
                ('note', models.TextField(blank=True)),
                ('started_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('ended_at', models.DateTimeField(blank=True, null=True)),
                ('is_active', models.BooleanField(db_index=True, default=True)),
                ('seat', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='maintenance_records', to='halls.seat')),
            ],
            options={
                'verbose_name': 'Seat Maintenance',
                'verbose_name_plural': 'Seat Maintenance Records',
                'ordering': ['-started_at'],
            },
        ),
        # AllocationCall (from 0004)
        migrations.CreateModel(
            name='AllocationCall',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('call_id', models.CharField(db_index=True, help_text='6-digit id: YYYY + 2-digit call number, e.g. 202601.', max_length=6, unique=True)),
                ('year', models.PositiveIntegerField(db_index=True)),
                ('sequence', models.PositiveSmallIntegerField(help_text='Call number within the year (from last two digits).')),
                ('is_active', models.BooleanField(db_index=True, default=False, help_text='Only one call can be active at a time.')),
                ('imported_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('imported_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='allocation_calls', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Allocation Call',
                'verbose_name_plural': 'Allocation Calls',
                'ordering': ['-year', '-sequence'],
            },
        ),
        # SeatAssignment (from 0001 + 0002 released_reason)
        migrations.CreateModel(
            name='SeatAssignment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('student_id', models.CharField(db_index=True, help_text='Student ID / Roll from the (separate) student table.', max_length=50)),
                ('order', models.PositiveSmallIntegerField(choices=[(1, 'Primary'), (2, 'Secondary')], default=1, help_text='Primary or Secondary student for a shared seat.')),
                ('assigned_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('is_active', models.BooleanField(db_index=True, default=True)),
                ('released_at', models.DateTimeField(blank=True, null=True)),
                ('released_reason', models.ForeignKey(blank=True, help_text='Reason selected when the seat was released from this student.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='assignments', to='allocations.seatreleasereason')),
                ('seat', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='assignments', to='halls.seat')),
            ],
            options={
                'verbose_name': 'Seat Assignment',
                'verbose_name_plural': 'Seat Assignments',
                'ordering': ['-assigned_at'],
                'constraints': [models.UniqueConstraint(condition=models.Q(('is_active', True)), fields=('seat', 'student_id'), name='unique_active_assignment_per_student'), models.CheckConstraint(condition=models.Q(('order__in', [1, 2])), name='assignment_order_in_primary_secondary')],
            },
        ),
        # HallAllocation final state (from 0004 + 0005 + 0006 + 0007 merged — no merit_pos, ordering by call__call_id, student_id, unique per call)
        migrations.CreateModel(
            name='HallAllocation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('hall_code', models.CharField(db_index=True, help_text='Code of the hall allotted to the student.', max_length=6)),
                ('student_id', models.CharField(db_index=True, help_text='Student who received this allotment.', max_length=10)),
                ('call', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='allotments', to='allocations.allocationcall')),
            ],
            options={
                'verbose_name': 'Hall Allocation',
                'verbose_name_plural': 'Hall Allocations',
                'ordering': ['call__call_id', 'student_id'],
            },
        ),
        migrations.AddConstraint(
            model_name='allocationcall',
            constraint=models.UniqueConstraint(condition=models.Q(('is_active', True)), fields=('is_active',), name='unique_active_allocation_call'),
        ),
        migrations.AddConstraint(
            model_name='hallallocation',
            constraint=models.UniqueConstraint(fields=('call', 'student_id'), name='unique_student_per_call'),
        ),
    ]
