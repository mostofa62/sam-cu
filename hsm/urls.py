"""URL configuration for hsm project."""

from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path

from .admin_site import hsm_admin_site

urlpatterns = [
    # Django admin — superusers only (see hsm.admin_site.SuperuserAdminSite).
    path('admin/', hsm_admin_site.urls),
    path('', include('dashboard.urls')),
    path('manage/', include('adminpanel.urls')),
    path('allocations/', include('allocations.urls')),
    path('slips/', include('slips.urls')),
    path('accounts/', include('accounts.urls')),
    path('halls/', include('halls.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
