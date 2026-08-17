from django.contrib import admin

from .models import ActionChoices, SeatAssignment, SeatAssignmentLog, SeatMaintenance


@admin.register(SeatAssignment)
class SeatAssignmentAdmin(admin.ModelAdmin):
    list_display = ('student_id', 'seat', 'order', 'is_active', 'assigned_at', 'released_at')
    list_filter = ('is_active', 'order', 'seat__hall')
    search_fields = ('student_id', 'seat__seat_number', 'seat__room__name')
    list_editable = ('order', 'is_active')
    date_hierarchy = 'assigned_at'
    readonly_fields = ('assigned_at',)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        SeatAssignmentLog.objects.create(
            student_id=obj.student_id,
            seat=obj.seat,
            order=obj.order,
            action=ActionChoices.ASSIGNED if obj.is_active else ActionChoices.RELEASED,
            note='Changed via admin.',
            performed_by=request.user,
        )


@admin.register(SeatAssignmentLog)
class SeatAssignmentLogAdmin(admin.ModelAdmin):
    list_display = ('action', 'student_id', 'seat', 'order', 'performed_by', 'created_at')
    list_filter = ('action', 'order', 'created_at')
    search_fields = ('student_id', 'seat__seat_number', 'seat__room__name')
    date_hierarchy = 'created_at'
    readonly_fields = ('student_id', 'seat', 'order', 'action', 'note', 'performed_by', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SeatMaintenance)
class SeatMaintenanceAdmin(admin.ModelAdmin):
    list_display = ('seat', 'reason', 'is_active', 'started_at', 'ended_at')
    list_filter = ('is_active', 'seat__hall')
    search_fields = ('reason', 'seat__seat_number', 'seat__room__name')
    list_editable = ('is_active',)
    date_hierarchy = 'started_at'
