from django.core.management.base import BaseCommand

from halls.models import Block, Floor, Hall, Room, Seat

HALL_DATA = [
    # code, name, hall_type, minority
    ('HALALA', 'ALAOL HALL', 'M', 'N'),
    ('HALAFR', 'A. F. RAHMAN HALL', 'M', 'N'),
    ('HALSJL', 'SHAHJALAL HALL', 'M', 'N'),
    ('HALSMT', 'SHAH AMANAT HALL', 'M', 'N'),
    ('HALSUH', 'SUHRAWARDY HALL', 'M', 'N'),
    ('HALSNR', 'SHAMSUN NAHAR HALL', 'F', 'N'),
    ('HALRAB', 'SHAHEED ABDUR RAB HALL', 'M', 'N'),
    ('HALPRT', 'PRITILATA HALL', 'F', 'N'),
    ('HALKHZ', 'DESHNETRI BEGUM KHALEDA ZIA HALL', 'F', 'N'),
    ('HALBIJ', 'BIJOY 24 HALL', 'F', 'N'),
    ('HALFRD', 'SHAHEED FARHAD HOSSAIN HALL', 'M', 'N'),
    ('HALATS', 'ATISH DIPANKAR HALL', 'M', 'Y'),
    ('HALFAZ', 'NAWAB FAIZUNNESA HALL', 'F', 'Y'),
    ('HALSUR', 'MASTERDA SURJA SEN HALL', 'M', 'Y'),
    ('HALRCH', 'SHILPI RASHID CHOWDHURY HOSTEL', 'M', 'N'),
    ('HALSUR', 'MASTERDA SURJA SEN HALL', 'F', 'Y'),
    ('HALRCH', 'SHILPI RASHID CHOWDHURY HOSTEL', 'F', 'N'),
]

COLORS = [
    '#6366f1', '#8b5cf6', '#ec4899', '#ef4444', '#f97316',
    '#f59e0b', '#eab308', '#84cc16', '#22c55e', '#10b981',
    '#14b8a6', '#06b6d4', '#0ea5e9', '#3b82f6', '#a855f7',
    '#d946ef', '#f43f5e',
]


class Command(BaseCommand):
    help = 'Seed CU halls (only Hall rows). Use --clear to drop SAMPLE hall-associated data. Prompts for confirmation. Skips existing.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear', '--reverse', '--drop',
            action='store_true', dest='clear',
            help='Drop/wipe only the SAMPLE hall demo data (17 HALL_DATA codes) instead of seeding. Deletes sample halls and their dependent slips, assignments, seats, rooms, floors, blocks — leaves custom halls untouched.',
        )
        parser.add_argument(
            '--no-input', '--yes', '-y',
            action='store_true', dest='no_input',
            help='Skip confirmation prompt and proceed (useful for automation).',
        )

    def handle(self, *args, **options):
        clear = options.get('clear')
        no_input = options.get('no_input')

        if clear:
            # confirm before destructive clear — SAMPLE only
            if not no_input and not self._confirm(
                'This will DELETE only the SAMPLE Hall data (17 HALL_DATA codes) and their dependent records (slips, seat assignments, maintenance, seats, rooms, floors, blocks, HallAllocations). Custom halls will be kept. Continue?'
            ):
                self.stdout.write(self.style.WARNING('Aborted --clear. No data deleted.'))
                return
            count = self._wipe_sample_data()
            self.stdout.write(self.style.WARNING(f'Seed hall SAMPLE wiped/cleared (reverse) — {count} sample hall(s) and dependents removed; custom halls kept.'))
            return

        # seeding — skip existing, confirm
        if not no_input and not self._confirm(
            f'This will create {len(HALL_DATA)} halls from HALL_DATA (only Hall rows, no blocks/seats). Existing sample halls will be SKIPPED (updated). Continue?'
        ):
            self.stdout.write(self.style.WARNING('Aborted. No data changed.'))
            return

        created = 0
        skipped = 0
        halls = []
        for i, (code, name, hall_type, minority) in enumerate(HALL_DATA):
            hall, is_created = Hall.objects.update_or_create(
                code=code, hall_type=hall_type,
                defaults={
                    'name': name,
                    'minority': minority,
                    'color': COLORS[i % len(COLORS)],
                    'has_blocks': False,
                    'description': '',
                },
            )
            halls.append(hall)
            if is_created:
                created += 1
            else:
                skipped += 1

        self.stdout.write(self.style.SUCCESS(f'Created {created} new hall(s), skipped {skipped} existing (total {len(halls)} in HALL_DATA, only Hall rows — no blocks/floors/rooms/seats).'))
        if skipped:
            self.stdout.write(self.style.WARNING(f'{skipped} sample hall(s) already existed — skipped (no duplicate created).'))
        self.stdout.write(self.style.SUCCESS('Demo hall seeding complete. Next: python manage.py seed_managers --halls <code...> (e.g. --halls HALALA halafr)'))

    def _confirm(self, message):
        self.stdout.write(self.style.WARNING(message))
        try:
            ans = input('Type "yes" to confirm [y/N]: ').strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        return ans in ('y', 'yes')

    def _wipe_sample_data(self):
        """Delete only SAMPLE halls (HALL_DATA) and their dependents; custom halls untouched."""
        # collect sample hall ids (code + hall_type distinct)
        sample_halls = []
        for code, _name, hall_type, _minority in HALL_DATA:
            qs = Hall.objects.filter(code=code, hall_type=hall_type)
            sample_halls.extend(list(qs))
        sample_ids = [h.id for h in sample_halls]
        if not sample_ids:
            return 0

        # Slips protect halls (PROTECT) — delete only for sample halls
        try:
            from slips.models import Slip, SlipItem
            SlipItem.objects.filter(slip__hall_id__in=sample_ids).delete()
            Slip.objects.filter(hall_id__in=sample_ids).delete()
        except Exception:
            pass
        try:
            from allocations.models import SeatAssignmentLog, SeatMaintenance, SeatAssignment
            # SeatAssignmentLog/SeatMaintenance via seat__hall_id
            SeatAssignmentLog.objects.filter(seat__hall_id__in=sample_ids).delete()
            SeatMaintenance.objects.filter(seat__hall_id__in=sample_ids).delete()
            SeatAssignment.objects.filter(seat__hall_id__in=sample_ids).delete()
        except Exception:
            pass
        try:
            from allocations.models import HallAllocation
            # hall_code is char, match sample codes
            sample_codes = {code for code, _, _, _ in HALL_DATA}
            HallAllocation.objects.filter(hall_code__in=sample_codes).delete()
        except Exception:
            pass
        try:
            Seat.objects.filter(hall_id__in=sample_ids).delete()
            Room.objects.filter(hall_id__in=sample_ids).delete()
            Floor.objects.filter(hall_id__in=sample_ids).delete()
            Block.objects.filter(hall_id__in=sample_ids).delete()
        except Exception:
            pass
        # finally halls
        deleted, _ = Hall.objects.filter(id__in=sample_ids).delete()
        return deleted

    def _wipe_demo_data(self):
        # legacy: now delegates to sample wipe (kept for compatibility)
        return self._wipe_sample_data()
