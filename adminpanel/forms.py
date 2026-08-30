from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from accounts.models import ADMIN_GROUP_NAME
from allocations.models import SeatReleaseReason
from halls.models import Block, Floor, Hall, Room, Seat
from students.models import Student

User = get_user_model()

WIDGET_CLASSES = (
    'w-full px-4 py-3 rounded-lg border border-gray-300 '
    'focus:outline-none focus:ring-2 focus:ring-indigo-500'
)


def styled(widget=None, extra=None):
    attrs = {'class': WIDGET_CLASSES}
    if extra:
        attrs.update(extra)
    return widget(attrs=attrs) if widget else attrs


class HallForm(forms.ModelForm):
    class Meta:
        model = Hall
        fields = ('name', 'code', 'hall_type', 'minority', 'color', 'has_blocks', 'description')
        widgets = {
            'name': forms.TextInput(attrs={'class': WIDGET_CLASSES}),
            'code': forms.TextInput(attrs={'class': WIDGET_CLASSES}),
            'description': forms.Textarea(attrs={'rows': 3, 'class': WIDGET_CLASSES}),
        }


class BlockForm(forms.ModelForm):
    class Meta:
        model = Block
        fields = ('hall', 'name', 'color')
        widgets = {
            'hall': forms.Select(attrs={'class': WIDGET_CLASSES}),
            'name': forms.TextInput(attrs={'class': WIDGET_CLASSES}),
        }


class FloorForm(forms.ModelForm):
    class Meta:
        model = Floor
        fields = ('hall', 'block', 'name', 'color')
        widgets = {
            'hall': forms.Select(attrs={'class': WIDGET_CLASSES}),
            'block': forms.Select(attrs={'class': WIDGET_CLASSES}),
            'name': forms.TextInput(attrs={'class': WIDGET_CLASSES}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Blocks grouped per hall so a matching block can be picked without JS;
        # consistency is still enforced server-side in clean().
        self.fields['block'].queryset = Block.objects.select_related('hall').order_by('hall__name', 'name')

    def clean(self):
        cleaned = super().clean()
        hall = cleaned.get('hall')
        block = cleaned.get('block')
        if hall and block and block.hall_id != hall.id:
            raise ValidationError('The selected block belongs to a different hall.')
        return cleaned


class RoomForm(forms.ModelForm):
    class Meta:
        model = Room
        fields = ('hall', 'floor', 'name', 'capacity', 'color')
        widgets = {
            'hall': forms.Select(attrs={'class': WIDGET_CLASSES}),
            'floor': forms.Select(attrs={'class': WIDGET_CLASSES}),
            'name': forms.TextInput(attrs={'class': WIDGET_CLASSES}),
            'capacity': forms.NumberInput(attrs={'class': WIDGET_CLASSES, 'min': 0}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['floor'].queryset = (
            Floor.objects.select_related('hall', 'block').order_by('hall__name', 'name')
        )
        self._group_floors()

    def _group_floors(self):
        """Render floor options inside <optgroup label="Hall"> blocks."""
        floors = list(self.fields['floor'].queryset)
        grouped = {}
        for floor in floors:
            prefix = f'{floor.block.name} / {floor.name}' if floor.block_id else floor.name
            grouped.setdefault(floor.hall.name, []).append((floor.pk, prefix))
        self.fields['floor'].choices = [('', 'Select floor')] + [
            (hall_name, opts) for hall_name, opts in grouped.items()
        ]

    def clean(self):
        cleaned = super().clean()
        hall = cleaned.get('hall')
        floor = cleaned.get('floor')
        if hall and floor and floor.hall_id != hall.id:
            raise ValidationError('The selected floor belongs to a different hall.')
        return cleaned


class SeatForm(forms.ModelForm):
    class Meta:
        model = Seat
        fields = ('hall', 'room', 'seat_number', 'is_active')
        widgets = {
            'hall': forms.Select(attrs={'class': WIDGET_CLASSES}),
            'room': forms.Select(attrs={'class': WIDGET_CLASSES}),
            'seat_number': forms.TextInput(attrs={'class': WIDGET_CLASSES}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        rooms = Room.objects.select_related('hall', 'floor__block').order_by('hall__name', 'name')
        grouped = {}
        for room in rooms:
            grouped.setdefault(room.hall.name, []).append((room.pk, room.compact_label))
        self.fields['room'].choices = [('', 'Select room')] + [
            (hall_name, opts) for hall_name, opts in grouped.items()
        ]

    def clean(self):
        cleaned = super().clean()
        hall = cleaned.get('hall')
        room = cleaned.get('room')
        if hall and room and room.hall_id != hall.id:
            raise ValidationError('The selected room belongs to a different hall.')
        return cleaned


class HallManagerForm(forms.ModelForm):
    """Create/edit a hall manager. Leave the password blank on edit to keep it."""
    password1 = forms.CharField(label='Password', required=False,
                                widget=forms.PasswordInput(attrs={'class': WIDGET_CLASSES}))
    password2 = forms.CharField(label='Password confirmation', required=False,
                                widget=forms.PasswordInput(attrs={'class': WIDGET_CLASSES}))

    class Meta:
        model = User
        fields = ('full_name', 'email', 'phone', 'managed_hall', 'is_active')
        widgets = {
            'full_name': forms.TextInput(attrs={'class': WIDGET_CLASSES}),
            'email': forms.EmailInput(attrs={'class': WIDGET_CLASSES}),
            'phone': forms.TextInput(attrs={'class': WIDGET_CLASSES}),
            'managed_hall': forms.Select(attrs={'class': WIDGET_CLASSES}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['managed_hall'].help_text = (
            'The single hall this manager controls. Leave empty for an account with no hall access.'
        )

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get('password1')
        password2 = cleaned.get('password2')
        if password1 or password2:
            if password1 != password2:
                raise ValidationError('Passwords do not match.')
            if len(password1) < 8:
                raise ValidationError('Password must be at least 8 characters long.')
        elif not self.instance.pk:
            raise ValidationError('A password is required for a new user.')
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_staff = False
        user.is_superuser = False
        password = self.cleaned_data.get('password1')
        if password:
            user.set_password(password)
        if commit:
            user.save()
        return user


class StudentForm(forms.ModelForm):
    """Curated edit form for master student data pulled from the external system."""

    class Meta:
        model = Student
        fields = (
            'student_id', 'name_en', 'name_bn', 'gender', 'religion', 'dob_ymd', 'bloodgroup',
            'nationality', 'nid', 'phone', 'session', 'hall_code', 'student_status',
            'perm_addr', 'perm_dist', 'pres_addr', 'pres_dist',
            'fname_en', 'fphone', 'mname_en', 'mphone',
        )
        widgets = {
            'student_id': forms.TextInput(attrs={'class': WIDGET_CLASSES}),
            'name_en': forms.TextInput(attrs={'class': WIDGET_CLASSES}),
            'name_bn': forms.TextInput(attrs={'class': WIDGET_CLASSES}),
            'gender': forms.Select(attrs={'class': WIDGET_CLASSES},
                                   choices=[('', '—'), ('MALE', 'Male'), ('FEMALE', 'Female')]),
            'religion': forms.TextInput(attrs={'class': WIDGET_CLASSES}),
            'dob_ymd': forms.TextInput(attrs={'class': WIDGET_CLASSES, 'placeholder': 'YYYY-MM-DD'}),
            'bloodgroup': forms.TextInput(attrs={'class': WIDGET_CLASSES, 'placeholder': 'A+'}),
            'nationality': forms.TextInput(attrs={'class': WIDGET_CLASSES}),
            'nid': forms.TextInput(attrs={'class': WIDGET_CLASSES}),
            'phone': forms.TextInput(attrs={'class': WIDGET_CLASSES}),
            'session': forms.TextInput(attrs={'class': WIDGET_CLASSES, 'placeholder': '2024-2025'}),
            'hall_code': forms.TextInput(attrs={'class': WIDGET_CLASSES}),
            'perm_addr': forms.Textarea(attrs={'rows': 2, 'class': WIDGET_CLASSES}),
            'pres_addr': forms.Textarea(attrs={'rows': 2, 'class': WIDGET_CLASSES}),
            'fname_en': forms.TextInput(attrs={'class': WIDGET_CLASSES}),
            'mname_en': forms.TextInput(attrs={'class': WIDGET_CLASSES}),
        }


class ReleaseReasonForm(forms.ModelForm):
    class Meta:
        model = SeatReleaseReason
        fields = ('name', 'is_active', 'sort_order')
        widgets = {
            'name': forms.TextInput(attrs={'class': WIDGET_CLASSES}),
            'sort_order': forms.NumberInput(attrs={'class': WIDGET_CLASSES, 'min': 0}),
        }
