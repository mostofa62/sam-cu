from django.core.management.base import BaseCommand

from allocations.models import SeatReleaseReason

REASONS = [
    'শিক্ষা সমাপন: কোর্স শেষ হওয়া বা ফাইনাল পরীক্ষা শেষ হওয়া',
    'নিয়মিত না থাকা: দীর্ঘদিন হলে না থাকা এবং অনুপস্থিত থাকা',
    'অনিয়ম: হলের শৃঙ্খলা পরিপন্থী কার্যকলাপে যুক্ত হওয়া',
    'ব্যক্তিগত কারণ: ব্যক্তিগত বা শারীরিক অসুস্থতা',
    'অন্য কোথাও বাসস্থান ঠিক হওয়া',
    'অন্য শিক্ষা প্রতিষ্ঠান এ সুযোগ পাওয়া',
]


class Command(BaseCommand):
    help = 'Seed SeatReleaseReason entries (idempotent, ordered by REASONS).'

    def handle(self, *args, **options):
        created = 0
        updated = 0
        for sort_order, name in enumerate(REASONS):
            _, is_created = SeatReleaseReason.objects.update_or_create(
                name=name,
                defaults={'sort_order': sort_order, 'is_active': True},
            )
            if is_created:
                created += 1
            else:
                updated += 1
        self.stdout.write(self.style.SUCCESS(
            f'SeatReleaseReason seeding complete: {created} created, {updated} updated (total {len(REASONS)}).'
        ))
