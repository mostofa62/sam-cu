import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from halls.models import Seat


class OrderChoices(models.IntegerChoices):
    PRIMARY = 1, 'Primary'
    SECONDARY = 2, 'Secondary'


class ActionChoices(models.TextChoices):
    ASSIGNED = 'assigned', 'Assigned'
    RELEASED = 'released', 'Released'


class AllocationCall(models.Model):
    """A hall-allocation call/cycle imported from the merit list.

    ``call_id`` is a 6-digit identifier ``YYYYNN`` — e.g. ``202601`` is the
    first allocation call of 2026 (``202607`` the seventh / July cycle).
    Importing a file makes its call the single active one; seat assignment is
    then validated against that active call's allotments.
    """

    CALL_ID_REGEX = re.compile(r'^\d{6}$')

    call_id = models.CharField(max_length=6, unique=True, db_index=True,
                               help_text='6-digit id: YYYY + 2-digit call number, e.g. 202601.')
    year = models.PositiveIntegerField(db_index=True)
    sequence = models.PositiveSmallIntegerField(help_text='Call number within the year (from last two digits).')
    is_active = models.BooleanField(default=False, db_index=True,
                                    help_text='Only one call can be active at a time.')
    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='allocation_calls',
    )
    imported_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = 'Allocation Call'
        verbose_name_plural = 'Allocation Calls'
        ordering = ['-year', '-sequence']
        constraints = [
            models.UniqueConstraint(
                fields=['is_active'],
                condition=models.Q(is_active=True),
                name='unique_active_allocation_call',
            ),
        ]

    def __str__(self):
        label = f'Call {self.call_id}'
        return f'{label} (active)' if self.is_active else label

    def clean(self):
        if self.call_id and not self.CALL_ID_REGEX.match(self.call_id):
            raise ValidationError({'call_id': 'Call ID must be exactly 6 digits in YYYYNN format, e.g. 202601.'})
        if self.sequence < 1:
            raise ValidationError({'sequence': 'Call number within the year must be at least 1.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @classmethod
    def active(cls):
        """The currently active call, or None when nothing has been imported yet."""
        return cls.objects.filter(is_active=True).first()

    @classmethod
    def parse_call_id(cls, call_id):
        """Split a YYYYNN call id into (year, sequence); raise ValueError otherwise."""
        if not cls.CALL_ID_REGEX.match(call_id or ''):
            raise ValueError('Call ID must be exactly 6 digits in YYYYNN format, e.g. 202601.')
        return int(call_id[:4]), int(call_id[4:])


class HallAllocation(models.Model):
    """One merit-list allotment row: which hall a student was allotted in a call.

    A student ID is unique across ALL calls — once allotted, the same student
    can never appear again in any later call.
    """

    call = models.ForeignKey(AllocationCall, on_delete=models.CASCADE,
                             related_name='allotments', db_index=True)
    hall_code = models.CharField(max_length=6, db_index=True,
                                 help_text='Code of the hall allotted to the student.')
    student_id = models.CharField(max_length=10, unique=True, db_index=True,
                                  help_text='Student who received this allotment. '
                                            'Unique across every allocation call.')
    merit_pos = models.IntegerField(help_text='Merit position used during the allocation.')

    class Meta:
        verbose_name = 'Hall Allocation'
        verbose_name_plural = 'Hall Allocations'
        ordering = ['call__call_id', 'merit_pos']
        constraints = [
            models.UniqueConstraint(
                fields=['student_id'],
                name='unique_student_across_calls',
            ),
        ]

    def __str__(self):
        return f'{self.student_id} -> {self.hall_code} (call {self.call.call_id}, merit {self.merit_pos})'

    def clean(self):
        from halls.models import Hall
        if self.hall_code and not Hall.objects.filter(code=self.hall_code).exists():
            raise ValidationError({'hall_code': f'No hall exists with code "{self.hall_code}".'})


class SeatReleaseReason(models.Model):
    """Predefined reason a manager selects when releasing a seat from a student."""

    name = models.CharField(max_length=255, unique=True,
                            help_text='Reason shown in the release dropdown.')
    is_active = models.BooleanField(default=True, db_index=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = 'Seat Release Reason'
        verbose_name_plural = 'Seat Release Reasons'
        ordering = ['sort_order', 'id']

    def __str__(self):
        return self.name


class SeatAssignment(models.Model):
    """Active allocation of a seat to a student. A seat may be shared by up to two students (primary/secondary)."""

    seat = models.ForeignKey(Seat, on_delete=models.CASCADE, related_name='assignments')
    student_id = models.CharField(max_length=50, db_index=True,
                                  help_text='Student ID / Roll from the (separate) student table.')
    order = models.PositiveSmallIntegerField(choices=OrderChoices.choices, default=OrderChoices.PRIMARY,
                                             help_text='Primary or Secondary student for a shared seat.')
    assigned_at = models.DateTimeField(default=timezone.now)
    is_active = models.BooleanField(default=True, db_index=True)
    released_at = models.DateTimeField(null=True, blank=True)
    released_reason = models.ForeignKey(
        SeatReleaseReason, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='assignments',
        help_text='Reason selected when the seat was released from this student.',
    )

    class Meta:
        verbose_name = 'Seat Assignment'
        verbose_name_plural = 'Seat Assignments'
        ordering = ['-assigned_at']
        constraints = [
            models.UniqueConstraint(
                fields=['seat', 'student_id'],
                condition=models.Q(is_active=True),
                name='unique_active_assignment_per_student',
            ),
            models.CheckConstraint(
                condition=models.Q(order__in=[1, 2]),
                name='assignment_order_in_primary_secondary',
            ),
        ]

    def __str__(self):
        return f'{self.student_id} -> {self.seat.seat_label} ({self.get_order_display()})'

    def clean(self):
        if self.is_active:
            # A seat can be shared by at most two active students.
            active_others = SeatAssignment.objects.filter(
                seat=self.seat, is_active=True,
            ).exclude(pk=self.pk).count()
            if active_others >= 2:
                raise ValidationError('This seat already has two active students. Release one first.')

            # A student can have only one active seat at a time.
            student_other = SeatAssignment.objects.filter(
                student_id=self.student_id, is_active=True,
            ).exclude(pk=self.pk).select_related(
                'seat__room__floor__block', 'seat__hall',
            ).first()
            if student_other:
                when = timezone.localtime(student_other.assigned_at).strftime('%d %b %Y, %I:%M %p')
                raise ValidationError(
                    f'Student {self.student_id} already has an active seat assigned — '
                    f'{student_other.seat.full_label} (allotted {when}).'
                )

            if self.seat.under_maintenance:
                raise ValidationError('This seat is on hold and cannot be assigned.')

    def save(self, *args, **kwargs):
        self.full_clean()
        if not self.is_active and not self.released_at:
            self.released_at = timezone.now()
        super().save(*args, **kwargs)


class SeatAssignmentLog(models.Model):
    """Immutable log of every assign / release action."""

    student_id = models.CharField(max_length=50, db_index=True)
    seat = models.ForeignKey(Seat, on_delete=models.PROTECT, related_name='assignment_logs')
    order = models.PositiveSmallIntegerField(choices=OrderChoices.choices, default=OrderChoices.PRIMARY)
    action = models.CharField(max_length=10, choices=ActionChoices.choices, db_index=True)
    note = models.CharField(max_length=255, blank=True)
    release_reason = models.ForeignKey(
        SeatReleaseReason, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='logs',
        help_text='Reason selected when a seat was released.',
    )
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='assignment_logs',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Seat Assignment Log'
        verbose_name_plural = 'Seat Assignment Logs'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_action_display()}: {self.student_id} @ {self.seat.seat_label}'


class SeatMaintenance(models.Model):
    """Maintenance record. While active, the seat is hidden from the assignment list."""

    seat = models.ForeignKey(Seat, on_delete=models.CASCADE, related_name='maintenance_records')
    reason = models.CharField(max_length=255, help_text='Reason for blocking the seat.')
    note = models.TextField(blank=True)
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        verbose_name = 'Seat Maintenance'
        verbose_name_plural = 'Seat Maintenance Records'
        ordering = ['-started_at']

    def __str__(self):
        return f'{self.seat.seat_label} - {self.reason}'

    def save(self, *args, **kwargs):
        if self.is_active and self.seat.assignments.filter(is_active=True).exists():
            raise ValidationError(
                'This seat has active student(s). Release the assignments before putting it on hold.'
            )
        if not self.is_active and not self.ended_at:
            self.ended_at = timezone.now()
        super().save(*args, **kwargs)
