from django.contrib import admin

from .models import Slip, SlipItem


class SlipItemInline(admin.TabularInline):
    model = SlipItem
    extra = 0


@admin.register(Slip)
class SlipAdmin(admin.ModelAdmin):
    list_display = ('serial_number', 'slip_type', 'student_id', 'hall_name_snapshot', 'seat_label_snapshot', 'total_amount', 'event_date', 'issued_at')
    list_filter = ('slip_type', 'hall', 'event_date', 'issued_at')
    search_fields = ('serial_number', 'student_id', 'student_name')
    inlines = [SlipItemInline]
    readonly_fields = ('serial_number', 'total_in_words', 'created_at', 'updated_at')


@admin.register(SlipItem)
class SlipItemAdmin(admin.ModelAdmin):
    list_display = ('slip', 'label', 'amount', 'sort_order')
    search_fields = ('label', 'slip__serial_number')
