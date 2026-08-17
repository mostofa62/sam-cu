from django.conf import settings


def site_settings(request):
    """Expose site branding settings from the environment to all templates."""
    header = getattr(settings, 'ADMIN_SITE_HEADER', 'CHITTAGONG UNIVERSITY HALL SEAT MANAGEMENT')
    title = getattr(settings, 'ADMIN_SITE_TITLE', 'CUHSM')
    index_title = getattr(settings, 'ADMIN_INDEX_TITLE', 'Administration')
    return {
        'SITE_HEADER': header,
        'SITE_TITLE': title,
        'SITE_INDEX_TITLE': index_title,
    }