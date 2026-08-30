from django.contrib import admin

from hsm.admin_site import hsm_admin_site

from .models import Student


@admin.register(Student, site=hsm_admin_site)
class StudentAdmin(admin.ModelAdmin):
    list_display = ('student_id', 'name_en', 'adm_roll', 'session', 'hsc_group', 'hall_code', 'student_status', 'user_id')
    list_filter = ('student_status', 'hsc_group', 'gender', 'session', 'hall_code')
    search_fields = ('student_id', 'name_en', 'name_bn', 'adm_roll', 'username', 'phone', 'nid')
    list_editable = ('student_status',)
    readonly_fields = ('username', 'user_id')
