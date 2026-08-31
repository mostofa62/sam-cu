from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


class SlipType(models.TextChoices):
    ASSIGN = 'assign', 'Assign'
    RELEASE = 'release', 'Release'


class Slip(models.Model):
    """Invoice/slip for assign or release of a seat.

    Each slip prints as two side-by-side copies (hall manager / student copy)
    sharing the same serial_number.
    """

    slip_type = models.CharField(max_length=10, choices=SlipType.choices, db_index=True)
    serial_number = models.CharField(max_length=30, unique=True, db_index=True,
                                     help_text='e.g. AS-2026-00001 or RS-2026-00001')
    hall = models.ForeignKey('halls.Hall', on_delete=models.PROTECT, related_name='slips')
    seat = models.ForeignKey('halls.Seat', on_delete=models.SET_NULL, null=True, blank=True,
                             related_name='slips')
    # Denormalized snapshot so slip remains correct even if seat/hall renamed.
    seat_label_snapshot = models.CharField(max_length=255, blank=True)
    hall_name_snapshot = models.CharField(max_length=150, blank=True)

    # Student snapshot
    student_id = models.CharField(max_length=50, db_index=True)
    student_name = models.CharField(max_length=150, blank=True)
    student_name_bn = models.CharField(max_length=150, blank=True)
    father_name = models.CharField(max_length=150, blank=True)
    father_name_bn = models.CharField(max_length=150, blank=True)
    subject = models.CharField(max_length=150, blank=True)
    subject_code = models.CharField(max_length=20, blank=True)

    # assignment / log linkage (optional, for quick navigation)
    assignment = models.ForeignKey('allocations.SeatAssignment', on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='slips')
    assignment_log = models.ForeignKey('allocations.SeatAssignmentLog', on_delete=models.SET_NULL,
                                       null=True, blank=True, related_name='slips')

    # Total is computed from items; stored for fast display and serial integrity.
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    total_in_words = models.CharField(max_length=500, blank=True,
                                      help_text='Auto-generated from total_amount')

    # Signature / issued info
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                  null=True, blank=True, related_name='issued_slips')
    issued_at = models.DateTimeField(default=timezone.now, db_index=True)
    # Effective assign/release date-time shown on slip (separate from slip issue date)
    event_date = models.DateTimeField(default=timezone.now, db_index=True,
                                      help_text='Assign / Release date-time printed on the slip')
    # Auto signature: name shown under signature line. Default = issued_by.full_name
    signature_name = models.CharField(max_length=150, blank=True,
                                      help_text='Name printed under signature line')
    signature_title = models.CharField(max_length=150, blank=True, default='Hall Manager / Provost',
                                       help_text='Title under signature')
    remarks = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Slip'
        verbose_name_plural = 'Slips'
        ordering = ['-issued_at', '-id']

    def __str__(self):
        return f'{self.serial_number} ({self.get_slip_type_display()}) - {self.student_id}'

    def recalculate_total(self, save=False):
        total = sum((i.amount for i in self.items.all()), Decimal('0.00'))
        self.total_amount = total
        self.total_in_words = amount_to_words(total)
        if save:
            self.save(update_fields=['total_amount', 'total_in_words', 'updated_at'])

    def save(self, *args, **kwargs):
        if not self.serial_number:
            self.serial_number = generate_serial(self.slip_type)
        # Snapshot hall/seat labels if not set
        if self.hall_id and not self.hall_name_snapshot:
            try:
                self.hall_name_snapshot = self.hall.name
            except Exception:
                pass
        if self.seat_id and not self.seat_label_snapshot:
            try:
                self.seat_label_snapshot = self.seat.full_label
            except Exception:
                self.seat_label_snapshot = self.seat.seat_label if self.seat else ''
        # Auto-derive event_date from linked SeatAssignment when available (no manual input)
        if self.assignment_id:
            try:
                # Ensure assignment is fetched fresh
                from allocations.models import SeatAssignment as SA
                ass = SA.objects.filter(pk=self.assignment_id).first()
                if ass:
                    if self.slip_type == SlipType.ASSIGN and ass.assigned_at:
                        self.event_date = ass.assigned_at
                    elif self.slip_type == SlipType.RELEASE and ass.released_at:
                        self.event_date = ass.released_at
                    elif ass.assigned_at:
                        # fallback
                        self.event_date = ass.assigned_at
            except Exception:
                pass
        elif self.student_id:
            # No explicit assignment link — try to find the relevant SeatAssignment for this student/seat
            try:
                from allocations.models import SeatAssignment as SA
                qs = SA.objects.filter(student_id=self.student_id)
                if self.seat_id:
                    qs = qs.filter(seat_id=self.seat_id)
                # For release, prefer the just-released (inactive) with released_at; for assign, active
                if self.slip_type == SlipType.RELEASE:
                    cand = qs.filter(released_at__isnull=False).order_by('-released_at').first()
                    if cand and cand.released_at:
                        self.event_date = cand.released_at
                        if not self.assignment_id:
                            self.assignment_id = cand.pk
                    else:
                        cand = qs.order_by('-assigned_at').first()
                        if cand and cand.assigned_at:
                            self.event_date = cand.assigned_at
                            if not self.assignment_id:
                                self.assignment_id = cand.pk
                else:
                    cand = qs.filter(is_active=True).order_by('-assigned_at').first() or qs.order_by('-assigned_at').first()
                    if cand and cand.assigned_at:
                        self.event_date = cand.assigned_at
                        if not self.assignment_id:
                            self.assignment_id = cand.pk
            except Exception:
                pass
        # Auto signature name
        if not self.signature_name and self.issued_by_id:
            try:
                self.signature_name = self.issued_by.full_name or str(self.issued_by)
            except Exception:
                pass
        # Keep total_in_words in sync when total_amount is set directly
        if self.total_amount is not None:
            self.total_in_words = amount_to_words(self.total_amount)
        super().save(*args, **kwargs)


class SlipItem(models.Model):
    """Fee/expense row inside a slip."""

    slip = models.ForeignKey(Slip, on_delete=models.CASCADE, related_name='items')
    label = models.CharField(max_length=255, help_text='e.g. দরিদ্র খাতে')
    label_en = models.CharField(max_length=255, blank=True, help_text='Optional English alias')
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = 'Slip Item'
        verbose_name_plural = 'Slip Items'
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f'{self.label}: {self.amount}'


# Default expense rows (Bengali) requested in spec
DEFAULT_SLIP_LABELS = [
    'দরিদ্র খাতে',
    'তৈজসপত্র বাবদ',
    'জামানত বাবদ',
    "ভোজনালয়ের অগ্রিম বাবদ",
]

DEFAULT_SLIP_LABELS_EN = {
    'দরিদ্র খাতে': 'Poor Fund',
    'তৈজসপত্র বাবদ': 'Utensils / Equipment',
    'জামানত বাবদ': 'Security Deposit',
    "ভোজনালয়ের অগ্রিম বাবদ": 'Dining Advance',
}


def generate_serial(slip_type):
    """Generate next serial atomically-ish: AS-YYYY-NNNNN or RS-YYYY-NNNNN.

    Uses count + 1 within current year/type. Race is mitigated by unique constraint retry.
    """
    prefix = 'AS' if slip_type == SlipType.ASSIGN else 'RS'
    year = timezone.now().year
    base = f'{prefix}-{year}-'
    # Find max sequence for this year/prefix
    last = Slip.objects.filter(serial_number__startswith=base).order_by('-serial_number').first()
    if last:
        try:
            seq = int(last.serial_number.split('-')[-1]) + 1
        except Exception:
            seq = Slip.objects.filter(serial_number__startswith=base).count() + 1
    else:
        seq = 1
    return f'{base}{seq:05d}'


def amount_to_words(amount):
    """Convert amount to words: English + Bengali Taka phrasing.

    e.g. 1250.50 -> 'One Thousand Two Hundred Fifty Taka and Fifty Paisa Only'
    Handles up to 99,99,99,999. Falls back to simple formatting for edge cases.
    """
    try:
        # Normalize
        d = Decimal(str(amount)).quantize(Decimal('0.01'))
    except Exception:
        return ''
    if d == 0:
        return 'Zero Taka Only'
    taka = int(d)
    paisa = int((d - taka) * 100)

    words_taka = number_to_words_en(taka)
    result = f'{words_taka} Taka' if words_taka else 'Zero Taka'
    if paisa:
        words_paisa = number_to_words_en(paisa)
        result += f' and {words_paisa} Paisa'
    result += ' Only'
    return result


def number_to_words_en(n):
    """Small English converter 0..999999999."""
    if n == 0:
        return 'Zero'
    units = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine',
             'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen',
             'Seventeen', 'Eighteen', 'Nineteen']
    tens = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']

    def _under_1000(num):
        parts = []
        if num >= 100:
            parts.append(units[num // 100] + ' Hundred')
            num %= 100
        if num >= 20:
            parts.append(tens[num // 10])
            if num % 10:
                parts[-1] += ' ' + units[num % 10]
        elif num > 0:
            parts.append(units[num])
        return ' '.join(parts)

    parts = []
    scales = [(10000000, 'Crore'), (100000, 'Lakh'), (1000, 'Thousand')]
    for scale_val, scale_name in scales:
        if n >= scale_val:
            count = n // scale_val
            parts.append(_under_1000(count) + f' {scale_name}')
            n %= scale_val
    if n > 0:
        parts.append(_under_1000(n))
    return ' '.join(parts)
