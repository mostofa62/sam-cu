"""Django admin site reserved for superusers only.

Regular (non-superuser) administrators use the in-app admin panel at
/manage/ instead; they are never allowed past this admin's login.
"""
from django.contrib.admin import AdminSite


class SuperuserAdminSite(AdminSite):
    """An AdminSite that only superuser staff can ever log into."""

    def has_permission(self, request):
        return (
            request.user.is_active
            and request.user.is_staff
            and request.user.is_superuser
        )


hsm_admin_site = SuperuserAdminSite(name='admin')
hsm_admin_site.site_header = 'CHITTAGONG UNIVERSITY HALL SEAT MANAGEMENT'
hsm_admin_site.site_title = 'CUHSM'
hsm_admin_site.index_title = 'Administration'
