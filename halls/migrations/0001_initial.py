# Squashed initial — generated from 0001_initial + 0002_hall_hall_type_... (2026-09-01)
# Represents final state of halls models.

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Block',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('name', models.CharField(max_length=100)),
                ('color', models.CharField(default='#22c55e', help_text='Color used to differentiate this block.', max_length=9, validators=[django.core.validators.RegexValidator(message='Enter a valid hex color, e.g. #6366f1.', regex='^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$')])),
            ],
            options={
                'verbose_name': 'Block',
                'verbose_name_plural': 'Blocks',
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='Hall',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('name', models.CharField(max_length=150)),
                ('code', models.CharField(blank=True, max_length=20, null=True)),
                ('hall_type', models.CharField(choices=[('M', 'Male'), ('F', 'Female')], default='M', help_text='Male or female hall.', max_length=1)),
                ('minority', models.CharField(choices=[('Y', 'Yes (Minority / Ethnic)'), ('N', 'No')], default='N', help_text='Minority / ethnic hall flag.', max_length=1)),
                ('color', models.CharField(default='#6366f1', help_text='Color used to differentiate this hall.', max_length=9, validators=[django.core.validators.RegexValidator(message='Enter a valid hex color, e.g. #6366f1.', regex='^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$')])),
                ('has_blocks', models.BooleanField(default=False, help_text='Check if this hall is divided into blocks.')),
                ('description', models.TextField(blank=True)),
            ],
            options={
                'verbose_name': 'Hall',
                'verbose_name_plural': 'Halls',
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='Floor',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('name', models.CharField(help_text='e.g. Ground Floor, 1st Floor', max_length=100)),
                ('color', models.CharField(default='#f59e0b', help_text='Color used to differentiate this floor.', max_length=9, validators=[django.core.validators.RegexValidator(message='Enter a valid hex color, e.g. #6366f1.', regex='^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$')])),
                ('block', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='floors', to='halls.block')),
                ('hall', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='floors', to='halls.hall')),
            ],
            options={
                'verbose_name': 'Floor',
                'verbose_name_plural': 'Floors',
                'ordering': ['hall', 'block', 'name'],
            },
        ),
        migrations.AddField(
            model_name='block',
            name='hall',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='blocks', to='halls.hall'),
        ),
        migrations.CreateModel(
            name='Room',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('name', models.CharField(help_text='e.g. 201, AB-101', max_length=100)),
                ('capacity', models.PositiveIntegerField(default=0, help_text='Maximum number of seats.')),
                ('color', models.CharField(default='#8b5cf6', help_text='Color used to differentiate this room.', max_length=9, validators=[django.core.validators.RegexValidator(message='Enter a valid hex color, e.g. #6366f1.', regex='^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$')])),
                ('floor', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='rooms', to='halls.floor')),
                ('hall', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='rooms', to='halls.hall')),
            ],
            options={
                'verbose_name': 'Room',
                'verbose_name_plural': 'Rooms',
                'ordering': ['hall', 'floor', 'name'],
            },
        ),
        migrations.CreateModel(
            name='Seat',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('seat_number', models.CharField(max_length=50)),
                ('is_active', models.BooleanField(default=True, help_text='Uncheck to permanently disable this seat.')),
                ('hall', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='seats', to='halls.hall')),
                ('room', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='seats', to='halls.room')),
            ],
            options={
                'verbose_name': 'Seat',
                'verbose_name_plural': 'Seats',
                'ordering': ['room', 'seat_number'],
            },
        ),
        migrations.AddConstraint(
            model_name='hall',
            constraint=models.UniqueConstraint(fields=('code', 'hall_type'), name='unique_hall_code_per_type'),
        ),
        migrations.AddConstraint(
            model_name='floor',
            constraint=models.UniqueConstraint(condition=models.Q(('block__isnull', False)), fields=('block', 'name'), name='unique_floor_name_per_block'),
        ),
        migrations.AddConstraint(
            model_name='block',
            constraint=models.UniqueConstraint(fields=('hall', 'name'), name='unique_block_name_per_hall'),
        ),
        migrations.AddConstraint(
            model_name='room',
            constraint=models.UniqueConstraint(fields=('floor', 'name'), name='unique_room_name_per_floor'),
        ),
        migrations.AddConstraint(
            model_name='seat',
            constraint=models.UniqueConstraint(fields=('room', 'seat_number'), name='unique_seat_number_per_room'),
        ),
    ]
