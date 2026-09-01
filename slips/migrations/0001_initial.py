# Squashed initial — generated from 0001_initial + 0002_slip_event_date + 0003_slip_bengali_names (2026-09-01)
# Represents final state of slips models.

import django.db.models.deletion
import django.utils.timezone
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('allocations', '0001_initial'),
        ('halls', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Slip',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slip_type', models.CharField(choices=[('assign', 'Assign'), ('release', 'Release')], db_index=True, max_length=10)),
                ('serial_number', models.CharField(db_index=True, help_text='e.g. AS-2026-00001 or RS-2026-00001', max_length=30, unique=True)),
                ('seat_label_snapshot', models.CharField(blank=True, max_length=255)),
                ('hall_name_snapshot', models.CharField(blank=True, max_length=150)),
                ('student_id', models.CharField(db_index=True, max_length=50)),
                ('student_name', models.CharField(blank=True, max_length=150)),
                ('student_name_bn', models.CharField(blank=True, max_length=150)),
                ('father_name', models.CharField(blank=True, max_length=150)),
                ('father_name_bn', models.CharField(blank=True, max_length=150)),
                ('subject', models.CharField(blank=True, max_length=150)),
                ('subject_code', models.CharField(blank=True, max_length=20)),
                ('total_amount', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=10)),
                ('total_in_words', models.CharField(blank=True, help_text='Auto-generated from total_amount', max_length=500)),
                ('issued_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('event_date', models.DateTimeField(db_index=True, default=django.utils.timezone.now, help_text='Assign / Release date-time printed on the slip')),
                ('signature_name', models.CharField(blank=True, help_text='Name printed under signature line', max_length=150)),
                ('signature_title', models.CharField(blank=True, default='Hall Manager / Provost', help_text='Title under signature', max_length=150)),
                ('remarks', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('assignment', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='slips', to='allocations.seatassignment')),
                ('assignment_log', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='slips', to='allocations.seatassignmentlog')),
                ('hall', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='slips', to='halls.hall')),
                ('issued_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='issued_slips', to=settings.AUTH_USER_MODEL)),
                ('seat', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='slips', to='halls.seat')),
            ],
            options={
                'verbose_name': 'Slip',
                'verbose_name_plural': 'Slips',
                'ordering': ['-issued_at', '-id'],
            },
        ),
        migrations.CreateModel(
            name='SlipItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('label', models.CharField(help_text='e.g. দরিদ্র খাতে', max_length=255)),
                ('label_en', models.CharField(blank=True, help_text='Optional English alias', max_length=255)),
                ('amount', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=10)),
                ('sort_order', models.PositiveSmallIntegerField(default=0)),
                ('slip', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='slips.slip')),
            ],
            options={
                'verbose_name': 'Slip Item',
                'verbose_name_plural': 'Slip Items',
                'ordering': ['sort_order', 'id'],
            },
        ),
    ]
