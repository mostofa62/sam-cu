from django.db import migrations

REASONS = [
    'শিক্ষা সমাপন: কোর্স শেষ হওয়া বা ফাইনাল পরীক্ষা শেষ হওয়া',
    'নিয়মিত না থাকা: দীর্ঘদিন হলে না থাকা এবং অনুপস্থিত থাকা',
    'অনিয়ম: হলের শৃঙ্খলা পরিপন্থী কার্যকলাপে যুক্ত হওয়া',
    'ব্যক্তিগত কারণ: ব্যক্তিগত বা শারীরিক অসুস্থতা',
    'অন্য কোথাও বাসস্থান ঠিক হওয়া',
]


def seed_release_reasons(apps, schema_editor):
    SeatReleaseReason = apps.get_model('allocations', 'SeatReleaseReason')
    for sort_order, name in enumerate(REASONS):
        SeatReleaseReason.objects.update_or_create(
            name=name,
            defaults={'sort_order': sort_order, 'is_active': True},
        )


def unseed_release_reasons(apps, schema_editor):
    SeatReleaseReason = apps.get_model('allocations', 'SeatReleaseReason')
    SeatReleaseReason.objects.filter(name__in=REASONS).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('allocations', '0002_seatreleasereason_seatassignment_released_reason_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_release_reasons, reverse_code=unseed_release_reasons),
    ]