from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models

hex_color_validator = RegexValidator(
    regex=r'^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$',
    message='Enter a valid hex color, e.g. #6366f1.',
)


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Hall(TimeStampedModel):
    """A student hall. Blocks are optional for a hall."""

    class HallType(models.TextChoices):
        MALE = 'M', 'Male'
        FEMALE = 'F', 'Female'

    class MinorityFlag(models.TextChoices):
        YES = 'Y', 'Yes (Minority / Ethnic)'
        NO = 'N', 'No'

    name = models.CharField(max_length=150)
    code = models.CharField(max_length=20, blank=True, null=True)
    hall_type = models.CharField(
        max_length=1, choices=HallType.choices, default=HallType.MALE,
        help_text='Male or female hall.',
    )
    minority = models.CharField(
        max_length=1, choices=MinorityFlag.choices, default=MinorityFlag.NO,
        help_text='Minority / ethnic hall flag.',
    )
    color = models.CharField(max_length=9, validators=[hex_color_validator], default='#6366f1',
                             help_text='Color used to differentiate this hall.')
    has_blocks = models.BooleanField(default=False, help_text='Check if this hall is divided into blocks.')
    description = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Hall'
        verbose_name_plural = 'Halls'
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['code', 'hall_type'], name='unique_hall_code_per_type'),
        ]

    def __str__(self):
        return self.name

    @property
    def total_rooms(self):
        return self.rooms.count()

    @property
    def total_seats(self):
        return self.seats.count()

    @property
    def free_seats(self):
        from allocations.models import SeatAssignment
        assigned_ids = SeatAssignment.objects.filter(is_active=True).values_list('seat_id', flat=True)
        return self.seats.exclude(id__in=assigned_ids).count()


class Block(TimeStampedModel):
    """Optional division of a hall (e.g. Shaheed Block, Provash Block)."""

    hall = models.ForeignKey(Hall, on_delete=models.CASCADE, related_name='blocks')
    name = models.CharField(max_length=100)
    color = models.CharField(max_length=9, validators=[hex_color_validator], default='#22c55e',
                             help_text='Color used to differentiate this block.')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_blocks')

    class Meta:
        verbose_name = 'Block'
        verbose_name_plural = 'Blocks'
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['hall', 'name'], name='unique_block_name_per_hall'),
        ]

    def __str__(self):
        return f'{self.hall.name} - {self.name}'

    def is_editable_by(self, user):
        if user.is_app_admin:
            return True
        return self.created_by_id == user.pk


class Floor(TimeStampedModel):
    """Floor inside a hall. Belongs to a block when the hall uses blocks, otherwise directly to the hall."""

    hall = models.ForeignKey(Hall, on_delete=models.CASCADE, related_name='floors')
    block = models.ForeignKey(Block, on_delete=models.SET_NULL, null=True, blank=True, related_name='floors')
    name = models.CharField(max_length=100, help_text='e.g. Ground Floor, 1st Floor')
    color = models.CharField(max_length=9, validators=[hex_color_validator], default='#f59e0b',
                             help_text='Color used to differentiate this floor.')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_floors')

    class Meta:
        verbose_name = 'Floor'
        verbose_name_plural = 'Floors'
        ordering = ['hall', 'block', 'name']
        constraints = [
            models.UniqueConstraint(fields=['block', 'name'], name='unique_floor_name_per_block',
                                    condition=models.Q(block__isnull=False)),
        ]

    def __str__(self):
        prefix = f'{self.block} / ' if self.block else f'{self.hall.name} / '
        return f'{prefix}{self.name}'

    def is_editable_by(self, user):
        if user.is_app_admin:
            return True
        return self.created_by_id == user.pk


class Room(TimeStampedModel):
    """Room inside a floor."""

    hall = models.ForeignKey(Hall, on_delete=models.CASCADE, related_name='rooms')
    floor = models.ForeignKey(Floor, on_delete=models.CASCADE, related_name='rooms')
    name = models.CharField(max_length=100, help_text='e.g. 201, AB-101')
    capacity = models.PositiveIntegerField(default=0, help_text='Maximum number of seats.')
    color = models.CharField(max_length=9, validators=[hex_color_validator], default='#8b5cf6',
                             help_text='Color used to differentiate this room.')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_rooms')

    class Meta:
        verbose_name = 'Room'
        verbose_name_plural = 'Rooms'
        ordering = ['hall', 'floor', 'name']
        constraints = [
            models.UniqueConstraint(fields=['floor', 'name'], name='unique_room_name_per_floor'),
        ]

    def __str__(self):
        return f'{self.floor} - Room {self.name}'

    @property
    def compact_label(self):
        """Room label without the hall name, e.g. 'Block A / Ground Floor - Room 101'."""
        floor = self.floor
        prefix = f'{floor.block.name} / {floor.name}' if floor.block_id else floor.name
        return f'{prefix} - Room {self.name}'

    def is_editable_by(self, user):
        if user.is_app_admin:
            return True
        return self.created_by_id == user.pk


class Seat(TimeStampedModel):
    """A physical seat inside a room."""

    hall = models.ForeignKey(Hall, on_delete=models.CASCADE, related_name='seats')
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='seats')
    seat_number = models.CharField(max_length=50)
    is_active = models.BooleanField(default=True, help_text='Uncheck to permanently disable this seat.')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_seats')

    class Meta:
        verbose_name = 'Seat'
        verbose_name_plural = 'Seats'
        ordering = ['room', 'seat_number']
        constraints = [
            models.UniqueConstraint(fields=['room', 'seat_number'], name='unique_seat_number_per_room'),
        ]

    def __str__(self):
        return f'{self.room} - Seat {self.seat_number}'

    def is_editable_by(self, user):
        if user.is_app_admin:
            return True
        return self.created_by_id == user.pk

    @property
    def seat_label(self):
        return f'{self.room.name}/{self.seat_number}'

    @property
    def full_label(self):
        """Fully-qualified label incl. hall, e.g. 'Hall X - Block A / Ground Floor - Room 101 - Seat 1'."""
        floor = self.room.floor
        prefix = f'{floor.block.name} / {floor.name}' if floor.block_id else floor.name
        return f'{self.hall.name} - {prefix} - Room {self.room.name} - Seat {self.seat_number}'

    @property
    def under_maintenance(self):
        return self.maintenance_records.filter(is_active=True).exists()

    @property
    def active_maintenance(self):
        return self.maintenance_records.filter(is_active=True).first()
