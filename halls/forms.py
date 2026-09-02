from django import forms

from .models import Block, Floor, Room, Seat

WIDGET = 'w-full px-4 py-3 rounded-lg border border-gray-300 focus:outline-none focus:ring-2 focus:ring-indigo-500'

class ManagerBlockForm(forms.ModelForm):
    class Meta:
        model = Block
        fields = ('hall', 'name', 'color')
        widgets = {
            'hall': forms.Select(attrs={'class': WIDGET}),
            'name': forms.TextInput(attrs={'class': WIDGET}),
        }
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            halls = user.visible_halls()
            self.fields['hall'].queryset = halls
            if halls.count() == 1 and not self.instance.pk:
                self.initial['hall'] = halls.first()

class ManagerFloorForm(forms.ModelForm):
    class Meta:
        model = Floor
        fields = ('hall', 'block', 'name', 'color')
        widgets = {
            'hall': forms.Select(attrs={'class': WIDGET}),
            'block': forms.Select(attrs={'class': WIDGET}),
            'name': forms.TextInput(attrs={'class': WIDGET}),
        }
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            halls = user.visible_halls()
            self.fields['hall'].queryset = halls
            self.fields['block'].queryset = Block.objects.filter(hall__in=halls)
            if halls.count() == 1 and not self.instance.pk:
                self.initial['hall'] = halls.first()
        # filter blocks per hall dynamically via JS handled separately; keep all visible for now
    def clean(self):
        cleaned = super().clean()
        hall = cleaned.get('hall')
        block = cleaned.get('block')
        if hall and block and block.hall_id != hall.pk:
            raise forms.ValidationError('Block belongs to a different hall.')
        return cleaned

class ManagerRoomForm(forms.ModelForm):
    class Meta:
        model = Room
        fields = ('hall', 'floor', 'name', 'capacity', 'color')
        widgets = {
            'hall': forms.Select(attrs={'class': WIDGET}),
            'floor': forms.Select(attrs={'class': WIDGET}),
            'name': forms.TextInput(attrs={'class': WIDGET}),
            'capacity': forms.NumberInput(attrs={'class': WIDGET, 'min': 0}),
        }
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            halls = user.visible_halls()
            self.fields['hall'].queryset = halls
            self.fields['floor'].queryset = Floor.objects.filter(hall__in=halls)
            if halls.count() == 1 and not self.instance.pk:
                self.initial['hall'] = halls.first()
    def clean(self):
        cleaned = super().clean()
        hall = cleaned.get('hall')
        floor = cleaned.get('floor')
        if hall and floor and floor.hall_id != hall.pk:
            raise forms.ValidationError('Floor belongs to a different hall.')
        return cleaned

class ManagerSeatForm(forms.ModelForm):
    class Meta:
        model = Seat
        fields = ('hall', 'room', 'seat_number', 'is_active')
        widgets = {
            'hall': forms.Select(attrs={'class': WIDGET}),
            'room': forms.Select(attrs={'class': WIDGET}),
            'seat_number': forms.TextInput(attrs={'class': WIDGET}),
        }
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            halls = user.visible_halls()
            self.fields['hall'].queryset = halls
            self.fields['room'].queryset = Room.objects.filter(hall__in=halls)
            if halls.count() == 1 and not self.instance.pk:
                self.initial['hall'] = halls.first()
    def clean(self):
        cleaned = super().clean()
        hall = cleaned.get('hall')
        room = cleaned.get('room')
        if hall and room and room.hall_id != hall.pk:
            raise forms.ValidationError('Room belongs to a different hall.')
        return cleaned
