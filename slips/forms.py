from decimal import Decimal, InvalidOperation

from django import forms

from halls.models import Hall, Seat

from .models import DEFAULT_SLIP_LABELS, Slip, SlipType


class SlipForm(forms.ModelForm):
    # Override to add hall/ seat pickers with limited queryset
    hall = forms.ModelChoiceField(
        queryset=Hall.objects.all(),
        widget=forms.Select(attrs={'class': 'w-full px-4 py-3 rounded-lg border border-slate-300', 'id': 'id_hall'}),
    )
    seat = forms.ModelChoiceField(
        queryset=Seat.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'w-full px-4 py-3 rounded-lg border border-slate-300', 'id': 'id_seat'}),
    )

    class Meta:
        model = Slip
        fields = ['slip_type', 'hall', 'seat', 'student_id', 'student_name', 'father_name',
                  'subject', 'subject_code', 'signature_name', 'signature_title', 'remarks']
        widgets = {
            'slip_type': forms.Select(attrs={'class': 'w-full px-4 py-3 rounded-lg border border-slate-300'}),
            'student_id': forms.TextInput(attrs={'class': 'w-full px-4 py-3 rounded-lg border border-slate-300', 'placeholder': 'e.g. 2101CSE001'}),
            'student_name': forms.TextInput(attrs={'class': 'w-full px-4 py-3 rounded-lg border border-slate-300', 'placeholder': 'Student name'}),
            'father_name': forms.TextInput(attrs={'class': 'w-full px-4 py-3 rounded-lg border border-slate-300', 'placeholder': "Father's name"}),
            'subject': forms.TextInput(attrs={'class': 'w-full px-4 py-3 rounded-lg border border-slate-300', 'placeholder': 'Subject / Department'}),
            'subject_code': forms.TextInput(attrs={'class': 'w-full px-4 py-3 rounded-lg border border-slate-300', 'placeholder': 'Subject code'}),
            'signature_name': forms.TextInput(attrs={'class': 'w-full px-4 py-3 rounded-lg border border-slate-300', 'placeholder': 'Auto from logged-in user if blank'}),
            'signature_title': forms.TextInput(attrs={'class': 'w-full px-4 py-3 rounded-lg border border-slate-300'}),
            'remarks': forms.Textarea(attrs={'class': 'w-full px-4 py-3 rounded-lg border border-slate-300', 'rows': 2, 'placeholder': 'Optional remarks'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user is not None:
            halls = user.visible_halls()
            self.fields['hall'].queryset = halls
            # single hall? auto select but keep visible maybe?
            if halls.count() == 1 and not self.instance.pk:
                self.fields['hall'].initial = halls.first()
            # limit seat queryset to visible halls initially
            self.fields['seat'].queryset = Seat.objects.filter(hall__in=halls).select_related('room', 'hall')[:500] if halls.exists() else Seat.objects.none()
        # If editing and seat exists, ensure its hall's seats are available
        if self.instance and self.instance.pk and self.instance.seat_id:
            # ensure queryset contains this seat
            qs = Seat.objects.filter(hall=self.instance.hall).select_related('room', 'hall')
            self.fields['seat'].queryset = qs
        # If bound and hall supplied, filter seat queryset by hall
        if self.is_bound:
            hall_id = self.data.get('hall')
            if hall_id:
                try:
                    self.fields['seat'].queryset = Seat.objects.filter(hall_id=hall_id).select_related('room', 'hall')
                except Exception:
                    pass


    def clean(self):
        cleaned = super().clean()
        # If user limited, ensure hall visible
        hall = cleaned.get('hall')
        if hall and self.user and not self.user.visible_halls().filter(pk=hall.pk).exists():
            self.add_error('hall', 'You do not have access to this hall.')
        seat = cleaned.get('seat')
        if seat and hall and seat.hall_id != hall.pk:
            self.add_error('seat', 'Seat does not belong to selected hall.')
        return cleaned

    def clean_student_id(self):
        sid = (self.cleaned_data.get('student_id') or '').strip()
        if not sid:
            raise forms.ValidationError('Student ID is required.')
        return sid


# Helper to parse dynamic items from POST

def parse_slip_items(post_data):
    """Parse labels/amounts arrays from POST.

    Expected keys: item_label[] and item_amount[] as repeated fields, or label_0 etc.
    We'll support item_label (getlist) and item_amount (getlist).
    """
    labels = post_data.getlist('item_label') if hasattr(post_data, 'getlist') else post_data.get('item_label', [])
    amounts = post_data.getlist('item_amount') if hasattr(post_data, 'getlist') else post_data.get('item_amount', [])
    # fallback comma handling already separate
    items = []
    for idx, label in enumerate(labels):
        label = (label or '').strip()
        amt_raw = amounts[idx] if idx < len(amounts) else '0'
        amt_raw = (amt_raw or '0').strip()
        if not label and not amt_raw:
            continue
        if not label:
            continue
        try:
            amt = Decimal(amt_raw) if amt_raw else Decimal('0')
        except (InvalidOperation, ValueError, TypeError):
            amt = Decimal('0')
        # negative not allowed?
        if amt < 0:
            amt = Decimal('0')
        items.append((label, amt))
    return items


def get_default_items_data():
    """Return list of (label, amount) for default rows with 0 amount."""
    return [(lbl, Decimal('0.00')) for lbl in DEFAULT_SLIP_LABELS]
