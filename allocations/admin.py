from django.contrib import admin

from hsm.admin_site import hsm_admin_site

from .models import (ActionChoices, AllocationCall, HallAllocation, SeatAssignment,
                     SeatAssignmentLog, SeatMaintenance, SeatReleaseReason)


@admin.register(AllocationCall, site=hsm_admin_site)
class AllocationCallAdmin(admin.ModelAdmin):
    list_display = ('call_id', 'year', 'sequence', 'is_active', 'allotment_count',
                    'imported_by', 'imported_at')
    list_filter = ('is_active', 'year')
    search_fields = ('call_id',)
    list_editable = ('is_active',)
    readonly_fields = ('imported_at',)

    @admin.display(description='Allotments')
    def allotment_count(self, obj):
        return obj.allotments.count()

    def save_model(self, request, obj, form, change):
        if obj.is_active:
            # Keep the "only one active call" rule when toggled from admin.
            AllocationCall.objects.exclude(pk=obj.pk).filter(is_active=True).update(is_active=False)
        super().save_model(request, obj, form, change)


@admin.register(HallAllocation, site=hsm_admin_site)
class HallAllocationAdmin(admin.ModelAdmin):
    list_display = ('student_id', 'hall_code', 'call', 'call_active')
    list_filter = ('call__is_active', 'call', 'hall_code')
    search_fields = ('student_id', 'hall_code')

    @admin.display(boolean=True, description='Call Active')
    def call_active(self, obj):
        return obj.call.is_active


@admin.register(SeatReleaseReason, site=hsm_admin_site)
class SeatReleaseReasonAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'sort_order')
    list_filter = ('is_active',)
    search_fields = ('name',)
    list_editable = ('is_active', 'sort_order')


@admin.register(SeatAssignment, site=hsm_admin_site)
class SeatAssignmentAdmin(admin.ModelAdmin):
    list_display = (
        'student_id', 'seat', 'order', 'is_active', 'assigned_at', 'released_at', 'released_reason',
    )
    list_filter = ('is_active', 'order', 'seat__hall', 'released_reason')
    search_fields = ('student_id', 'seat__seat_number', 'seat__room__name')
    list_editable = ('order', 'is_active')
    date_hierarchy = 'assigned_at'
    readonly_fields = ('assigned_at', 'released_reason')

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


@admin.register(SeatAssignmentLog, site=hsm_admin_site)
class SeatAssignmentLogAdmin(admin.ModelAdmin):
    list_display = ('action', 'student_id', 'seat', 'order', 'release_reason',
                    'performed_by', 'created_at')
    list_filter = ('action', 'order', 'release_reason', 'created_at')
    search_fields = ('student_id', 'seat__seat_number', 'seat__room__name')
    date_hierarchy = 'created_at'
    readonly_fields = ('student_id', 'seat', 'order', 'action', 'note', 'release_reason', 'performed_by', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SeatMaintenance, site=hsm_admin_site)
class SeatMaintenanceAdmin(admin.ModelAdmin):
    list_display = ('seat', 'reason', 'is_active', 'started_at', 'ended_at')
    list_filter = ('is_active', 'seat__hall')
    search_fields = ('reason', 'seat__seat_number', 'seat__room__name')
    list_editable = ('is_active',)
    date_hierarchy = 'started_at'
