from django import forms

from halls.models import Block, Floor, Hall, Room, Seat

from .models import SeatReleaseReason


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
            'placeholder': 'e.g. 2101CSE001',
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
        ).select_related('room')
        return available


class RevokeForm(forms.Form):
    student_id = forms.CharField(
        label='Student ID',
        max_length=50,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-3 rounded-lg border border-gray-300 focus:outline-none focus:ring-2 focus:ring-red-500',
            'placeholder': 'e.g. 2101CSE001',
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
