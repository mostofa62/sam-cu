from django.contrib import admin

from hsm.admin_site import hsm_admin_site

from .models import Student


@admin.register(Student, site=hsm_admin_site)
class StudentAdmin(admin.ModelAdmin):
    list_display = ('student_id', 'name_en', 'adm_roll', 'session', 'subject_code', 'subject', 'hsc_group', 'hall_code', 'student_status')
    list_filter = ('student_status', 'hsc_group', 'gender', 'session', 'hall_code', 'subject_code')
    search_fields = ('student_id', 'name_en', 'name_bn', 'adm_roll', 'username', 'phone', 'nid', 'subject_code', 'subject')
    list_editable = ('student_status',)
    readonly_fields = ('username',)
