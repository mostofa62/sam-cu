from django import forms

from halls.models import Block, Floor, Hall, Room, Seat

from .models import SeatMaintenanceReason, SeatReleaseReason


class HallChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f'{obj.name} ({obj.get_hall_type_display()})'


class RoomChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.compact_label


class SeatChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f'{obj.room.name} / Seat {obj.seat_number}'


class AssignForm(forms.Form):
    student_id = forms.CharField(
        label='Student ID',
        max_length=50,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-3 rounded-lg border border-gray-300 focus:outline-none focus:ring-2 focus:ring-indigo-500',
            'placeholder': 'e.g. 2601011001 or 24101001',
        }),
    )
    hall = HallChoiceField(
        queryset=Hall.objects.all(),
        empty_label='Select Hall',
        widget=forms.Select(attrs={'class': 'w-full px-4 py-3 rounded-lg border border-gray-300' , 'id': 'id_hall'}),
    )
    room = RoomChoiceField(
        queryset=Room.objects.none(),
        empty_label='Select Room',
        widget=forms.Select(attrs={'class': 'w-full px-4 py-3 rounded-lg border border-gray-300', 'id': 'id_room'}),
    )
    seat = SeatChoiceField(
        queryset=Seat.objects.none(),
        empty_label='Select Seat',
        widget=forms.Select(attrs={'class': 'w-full px-4 py-3 rounded-lg border border-gray-300', 'id': 'id_seat'}),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        # When a user manages exactly one hall the hall picker is pointless —
        # preset it and go straight to room -> seat. Multi-hall users and
        # superusers keep the visible hall selector.
        self.single_hall = None
        if user is not None:
            halls = user.visible_halls()
            self.fields['hall'].queryset = halls
            first_two = list(halls[:2])
            if len(first_two) == 1:
                self.single_hall = first_two[0]
        if self.single_hall is not None:
            self.fields['hall'].initial = self.single_hall
            self.fields['hall'].widget = forms.HiddenInput()
            self.fields['room'].queryset = Room.objects.filter(hall=self.single_hall).select_related('floor__block')
        if self.is_bound:
            hall_id = self.data.get('hall')
            if hall_id:
                self.fields['room'].queryset = Room.objects.filter(hall_id=hall_id).select_related('floor__block')
            room_id = self.data.get('room')
            if room_id:
                self.fields['seat'].queryset = self._available_seats(room_id)

    def clean(self):
        cleaned = super().clean()
        seat = cleaned.get('seat')
        if seat and self.user is not None:
            if not self.user.visible_halls().filter(pk=seat.hall_id).exists():
                self.add_error('seat', 'You do not have access to this hall.')
        return cleaned

    @staticmethod
    def _available_seats(room_id):
        from allocations.models import SeatAssignment
        seats = Seat.objects.filter(room_id=room_id, is_active=True)
        from django.db.models import Count
        occupied_ids = SeatAssignment.objects.filter(
            is_active=True,
            seat__room_id=room_id,
        ).values('seat_id').annotate(count=Count('id')).filter(count__gte=2).values_list('seat_id', flat=True)
        available = seats.exclude(id__in=occupied_ids).exclude(
            maintenance_records__is_active=True,
        ).select_related('room', 'room__floor__block', 'hall')
        return available


class RevokeForm(forms.Form):
    student_id = forms.CharField(
        label='Student ID',
        max_length=50,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-3 rounded-lg border border-gray-300 focus:outline-none focus:ring-2 focus:ring-red-500',
            'placeholder': 'e.g. 2601011001 or 24101001',
        }),
    )
    reason = forms.ModelChoiceField(
        label='Release Reason',
        queryset=SeatReleaseReason.objects.filter(is_active=True),
        empty_label='Select a release reason',
        widget=forms.Select(attrs={
            'class': 'w-full px-4 py-3 rounded-lg border border-gray-300 focus:outline-none focus:ring-2 focus:ring-red-500',
        }),
    )


class MaintenanceForm(forms.Form):
    hall = HallChoiceField(
        queryset=Hall.objects.all(),
        empty_label='Select Hall',
        widget=forms.Select(attrs={'class': 'w-full px-4 py-3 rounded-lg border border-gray-300', 'id': 'id_hall'}),
    )
    room = RoomChoiceField(
        queryset=Room.objects.none(),
        empty_label='Select Room',
        widget=forms.Select(attrs={'class': 'w-full px-4 py-3 rounded-lg border border-gray-300', 'id': 'id_room'}),
    )
    seat = forms.ModelChoiceField(
        queryset=Seat.objects.none(),
        empty_label='Select Seat',
        widget=forms.Select(attrs={'class': 'w-full px-4 py-3 rounded-lg border border-gray-300', 'id': 'id_seat'}),
    )
    reason = forms.ModelChoiceField(
        label='Maintenance Reason',
        queryset=SeatMaintenanceReason.objects.filter(is_active=True),
        empty_label='Select a maintenance reason',
        widget=forms.Select(attrs={
            'class': 'w-full px-4 py-3 rounded-lg border border-gray-300 focus:outline-none focus:ring-2 focus:ring-amber-500',
        }),
    )
    note = forms.CharField(
        required=False,
        label='Note (optional)',
        widget=forms.Textarea(attrs={
            'class': 'w-full px-4 py-3 rounded-lg border border-gray-300 focus:outline-none focus:ring-2 focus:ring-amber-500',
            'rows': 3,
            'placeholder': 'Additional details...',
        }),
    )
    started_at = forms.DateTimeField(
        label='Maintenance From',
        required=True,
        widget=forms.DateTimeInput(attrs={
            'type': 'datetime-local',
            'class': 'w-full px-4 py-3 rounded-lg border border-gray-300 focus:outline-none focus:ring-2 focus:ring-amber-500',
        }),
        help_text='When the maintenance starts.',
    )
    ended_at = forms.DateTimeField(
        label='Maintenance To',
        required=True,
        widget=forms.DateTimeInput(attrs={
            'type': 'datetime-local',
            'class': 'w-full px-4 py-3 rounded-lg border border-gray-300 focus:outline-none focus:ring-2 focus:ring-amber-500',
        }),
        help_text='When the maintenance is expected to end.',
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.single_hall = None
        if user is not None:
            halls = user.visible_halls()
            self.fields['hall'].queryset = halls
            first_two = list(halls[:2])
            if len(first_two) == 1:
                self.single_hall = first_two[0]
        if self.single_hall is not None:
            self.fields['hall'].initial = self.single_hall
            self.fields['hall'].widget = forms.HiddenInput()
            self.fields['room'].queryset = Room.objects.filter(hall=self.single_hall).select_related('floor__block')
        # Default started_at to now (local) for initial GET
        if not self.is_bound:
            from django.utils import timezone as _tz
            now_local = _tz.localtime(_tz.now())
            self.fields['started_at'].initial = now_local.strftime('%Y-%m-%dT%H:%M')
        if self.is_bound:
            hall_id = self.data.get('hall')
            if hall_id:
                self.fields['room'].queryset = Room.objects.filter(hall_id=hall_id).select_related('floor__block')
            room_id = self.data.get('room')
            if room_id:
                self.fields['seat'].queryset = Seat.objects.filter(room_id=room_id, is_active=True).select_related('room', 'hall')
        # custom label for seat field
        self.fields['seat'].label_from_instance = lambda obj: f'{obj.room.name} / Seat {obj.seat_number}'

    def clean(self):
        cleaned = super().clean()
        seat = cleaned.get('seat')
        if seat and self.user is not None:
            if not self.user.visible_halls().filter(pk=seat.hall_id).exists():
                self.add_error('seat', 'You do not have access to this hall.')
            if seat.assignments.filter(is_active=True).exists():
                self.add_error('seat', 'This seat has active student(s). Release them before putting it on hold.')
            if seat.maintenance_records.filter(is_active=True).exists():
                self.add_error('seat', 'This seat is already on hold.')
        started_at = cleaned.get('started_at')
        ended_at = cleaned.get('ended_at')
        if started_at and ended_at and ended_at <= started_at:
            self.add_error('ended_at', 'End time must be after start time.')
        return cleaned


class MaintenanceReasonForm(forms.ModelForm):
    class Meta:
        model = SeatMaintenanceReason
        fields = ('name', 'is_active', 'sort_order')
        widgets = {
            'name': forms.TextInput(attrs={'class': 'w-full px-4 py-3 rounded-lg border border-gray-300 focus:outline-none focus:ring-2 focus:ring-amber-500'}),
            'sort_order': forms.NumberInput(attrs={'class': 'w-full px-4 py-3 rounded-lg border border-gray-300 focus:outline-none focus:ring-2 focus:ring-amber-500', 'min': 0}),
        }


class ReleaseReasonForm(forms.ModelForm):
    class Meta:
        model = SeatReleaseReason
        fields = ('name', 'is_active', 'sort_order')
        widgets = {
            'name': forms.TextInput(attrs={'class': 'w-full px-4 py-3 rounded-lg border border-gray-300 focus:outline-none focus:ring-2 focus:ring-indigo-500'}),
            'sort_order': forms.NumberInput(attrs={'class': 'w-full px-4 py-3 rounded-lg border border-gray-300 focus:outline-none focus:ring-2 focus:ring-indigo-500', 'min': 0}),
        }


class ImportAllocationsForm(forms.Form):
    csv_file = forms.FileField(
        label='Allocation CSV File',
        help_text='Columns: call_id, hall_code, student_id — one row per allotted student.',
        widget=forms.ClearableFileInput(attrs={
            'class': 'w-full px-4 py-3 rounded-lg border border-gray-300 '
                     'file:mr-4 file:px-4 file:py-2 file:rounded-lg file:border-0 '
                     'file:bg-indigo-600 file:text-white file:font-semibold file:cursor-pointer '
                     'hover:file:bg-indigo-700',
            'accept': '.csv,text/csv',
        }),
    )

    def clean_csv_file(self):
        file = self.cleaned_data['csv_file']
        if file and not file.name.lower().endswith('.csv'):
            raise forms.ValidationError('Please upload a .csv file.')
        return file


class ResolveRequestForm(forms.ModelForm):
    class Meta:
        from .models import ResolveRequest
        model = ResolveRequest
        fields = ('request_type', 'reason')
        widgets = {
            'request_type': forms.Select(attrs={'class': 'w-full px-4 py-3 rounded-lg border border-gray-300 focus:outline-none focus:ring-2 focus:ring-indigo-500'}),
            'reason': forms.Textarea(attrs={'class': 'w-full px-4 py-3 rounded-lg border border-gray-300 focus:outline-none focus:ring-2 focus:ring-indigo-500', 'rows': 4, 'placeholder': 'Explain why this assign/release was mistaken...'}),
        }
        labels = {
            'request_type': 'Mistake Type',
            'reason': 'Reason / Details',
        }
