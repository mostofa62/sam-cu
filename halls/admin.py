from django.contrib import admin
from django.utils.html import format_html

from .models import Block, Floor, Hall, Room, Seat


@admin.register(Hall)
class HallAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'hall_type', 'minority', 'color_preview', 'has_blocks', 'total_seats', 'free_seats', 'created_at')
    list_editable = ('has_blocks',)
    list_filter = ('hall_type', 'minority', 'has_blocks')
    search_fields = ('name', 'code')

    @admin.display(description='Color')
    def color_preview(self, obj):
        return format_html('<span style="display:inline-block;width:18px;height:18px;border-radius:4px;background:{}"></span> {}', obj.color, obj.color)

    @admin.display(description='Vacant Seats')
    def free_seats(self, obj):
        return obj.free_seats


@admin.register(Block)
class BlockAdmin(admin.ModelAdmin):
    list_display = ('name', 'hall', 'color_preview')
    list_filter = ('hall',)
    search_fields = ('name', 'hall__name')

    @admin.display(description='Color')
    def color_preview(self, obj):
        return format_html('<span style="display:inline-block;width:18px;height:18px;border-radius:4px;background:{}"></span> {}', obj.color, obj.color)


@admin.register(Floor)
class FloorAdmin(admin.ModelAdmin):
    list_display = ('name', 'hall', 'block', 'color_preview')
    list_filter = ('hall', 'block')
    search_fields = ('name', 'hall__name', 'block__name')

    @admin.display(description='Color')
    def color_preview(self, obj):
        return format_html('<span style="display:inline-block;width:18px;height:18px;border-radius:4px;background:{}"></span> {}', obj.color, obj.color)


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ('name', 'hall', 'floor', 'capacity', 'color_preview')
    list_filter = ('hall', 'floor')
    search_fields = ('name', 'floor__name', 'hall__name')

    @admin.display(description='Color')
    def color_preview(self, obj):
        return format_html('<span style="display:inline-block;width:18px;height:18px;border-radius:4px;background:{}"></span> {}', obj.color, obj.color)


@admin.register(Seat)
class SeatAdmin(admin.ModelAdmin):
    list_display = ('seat_number', 'room', 'hall', 'status', 'is_active')
    list_filter = ('hall', 'room', 'is_active')
    search_fields = ('seat_number', 'room__name', 'hall__name')
    list_editable = ('is_active',)

    @admin.display(description='Status')
    def status(self, obj):
        if obj.under_maintenance:
            return 'On Hold'
        if obj.assignments.filter(is_active=True).exists():
            return 'Allotted'
        return 'Vacant'
