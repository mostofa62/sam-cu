# Squashed initial — generated from 0001_initial + 0002_remove_user_id + 0003_student_subject_... (2026-09-01)
# Represents final state of students models. Seed data removed — populate via CSV in production.

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Student',
            fields=[
                ('student_id', models.CharField(help_text='Student ID as the natural key.', max_length=10, primary_key=True, serialize=False)),
                ('adm_unit', models.CharField(blank=True, max_length=2, null=True)),
                ('adm_quota', models.CharField(blank=True, max_length=8, null=True)),
                ('adm_roll', models.CharField(blank=True, max_length=6, null=True)),
                ('hsc_group', models.CharField(blank=True, max_length=3, null=True)),
                ('adm_merit', models.CharField(blank=True, max_length=5, null=True)),
                ('username', models.CharField(blank=True, max_length=11, null=True)),
                ('session', models.CharField(blank=True, max_length=9, null=True)),
                ('entity_id', models.CharField(blank=True, max_length=5, null=True)),
                ('subject_id', models.CharField(blank=True, max_length=5, null=True)),
                ('subject_code', models.CharField(blank=True, max_length=6, null=True)),
                ('subject', models.CharField(blank=True, max_length=150, null=True)),
                ('name_en', models.CharField(blank=True, max_length=90, null=True)),
                ('name_bn', models.CharField(blank=True, max_length=90, null=True)),
                ('gender', models.CharField(blank=True, max_length=6, null=True)),
                ('religion', models.CharField(blank=True, max_length=15, null=True)),
                ('dob', models.CharField(blank=True, max_length=10, null=True)),
                ('dob_ymd', models.CharField(blank=True, max_length=11, null=True)),
                ('bloodgroup', models.CharField(blank=True, max_length=5, null=True)),
                ('nationality', models.CharField(blank=True, default='Bangladeshi', max_length=20)),
                ('nid', models.CharField(blank=True, max_length=30, null=True)),
                ('phone', models.CharField(blank=True, max_length=14, null=True)),
                ('both_address_same', models.IntegerField(default=0)),
                ('perm_addr', models.CharField(blank=True, max_length=458, null=True)),
                ('perm_dist', models.CharField(blank=True, max_length=50, null=True)),
                ('perm_pcode', models.CharField(blank=True, max_length=50, null=True)),
                ('pres_addr', models.CharField(blank=True, max_length=458, null=True)),
                ('pres_dist', models.CharField(blank=True, max_length=50, null=True)),
                ('pres_pcode', models.CharField(blank=True, max_length=50, null=True)),
                ('fname_en', models.CharField(blank=True, max_length=90, null=True)),
                ('fname_bn', models.CharField(blank=True, max_length=90, null=True)),
                ('fnid', models.CharField(blank=True, max_length=20, null=True)),
                ('foccupation', models.CharField(blank=True, max_length=50, null=True)),
                ('fphone', models.CharField(blank=True, max_length=14, null=True)),
                ('mname_en', models.CharField(blank=True, max_length=90, null=True)),
                ('mname_bn', models.CharField(blank=True, max_length=90, null=True)),
                ('mnid', models.CharField(blank=True, max_length=20, null=True)),
                ('mphone', models.CharField(blank=True, max_length=14, null=True)),
                ('rand_hash', models.CharField(blank=True, max_length=10, null=True)),
                ('hall_code', models.CharField(blank=True, max_length=6, null=True)),
                ('student_status', models.PositiveSmallIntegerField(choices=[(1, 'Active'), (2, 'Suspended'), (3, 'Cancelled'), (4, 'Graduated')], default=1, help_text='1 = active, 2 = suspended, 3 = cancelled, 4 = graduated')),
            ],
            options={
                'verbose_name': 'Student',
                'verbose_name_plural': 'Students',
                'ordering': ['student_id'],
            },
        ),
    ]
