from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import User
from halls.models import Hall

DEFAULT_PASSWORD = 'SamHallManager@202609'
DEFAULT_PHONE = '+8801670502283'
DOMAIN = 'cu.ac.bd'


class Command(BaseCommand):
    help = (
        'Create hall managers from hall codes. Email is derived from the hall code '
        '(e.g. HALAFR -> hallafr@cu.ac.bd, duplicate HALAFR -> hallafr1@cu.ac.bd). '
        'Case-insensitive. A code can be repeated to create multiple managers for the same hall.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--halls', nargs='+', default=None,
            help='Hall codes to assign managers to. Case-insensitive; duplicates create numbered emails (HALAFR HALAFR HALKHZ -> hallafr@cu.ac.bd, hallafr1@cu.ac.bd, halkhz@cu.ac.bd). When omitted the first two available are used.',
        )
        parser.add_argument(
            '--password', default=DEFAULT_PASSWORD,
            help=f'Password for every created manager (default: {DEFAULT_PASSWORD}).',
        )
        parser.add_argument(
            '--phone', default=DEFAULT_PHONE,
            help=f'Phone for every created manager (default: {DEFAULT_PHONE}).',
        )
        parser.add_argument(
            '--clear', '--reverse', '--drop',
            action='store_true', dest='clear',
            help='Drop/reverse: delete the demo manager users instead of creating them (clears previous data).',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options.get('clear'):
            # clear ONLY sample managers: emails derived from HALL_DATA hall codes
            # (hallcode@cu.ac.bd, hallcode1@cu.ac.bd ...) plus legacy manager.*@cu.ac.bd
            # custom managers (non-sample emails) are kept.
            from halls.management.commands.seed_hall import HALL_DATA
            sample_bases = {code.strip().lower() for code, _, _, _ in HALL_DATA}
            # collect sample emails to delete: hallcode@cu.ac.bd variants
            sample_local_bases = sample_bases
            qs = User.objects.filter(managed_hall__isnull=False, email__endswith=f'@{DOMAIN}')
            to_delete_ids = []
            for u in qs.iterator():
                local = (u.email.split('@')[0] or '').lower()
                # strip trailing digits for duplicate handling hallafr1 -> hallafr
                stripped = local.rstrip('0123456789')
                if stripped in sample_local_bases or local in sample_local_bases:
                    to_delete_ids.append(u.id)
            count = User.objects.filter(id__in=to_delete_ids).delete()[0] if to_delete_ids else 0
            # also legacy sample: manager.*@cu.ac.bd / @example.com (old random scheme) — only if code not sample, still sample
            from django.db.models import Q
            legacy_qs = User.objects.filter(email__startswith='manager.', email__endswith=f'@{DOMAIN}')
            # legacy are also sample, but keep custom if not sample base
            legacy_count = 0
            if legacy_qs.exists():
                legacy_count = legacy_qs.delete()[0]
            self.stdout.write(self.style.WARNING(f'Manager reverse complete: {count + legacy_count} SAMPLE demo manager user(s) deleted (hallcode@cu.ac.bd sample only; custom managers kept).'))
            return

        codes = options['halls'] or self._pick_default_codes()
        password = options['password']
        phone = options['phone']

        # resolve halls preserving order and duplicates, case-insensitive
        halls = [self._resolve_hall(code) for code in codes]
        if not halls:
            raise CommandError('At least one hall is required for the demo scenario.')

        # generate emails from hall codes, deduplicate with numeric suffix
        email_counts = {}
        managers = []
        for hall in halls:
            base_local = hall.code.strip().lower()
            cnt = email_counts.get(base_local, 0)
            if cnt == 0:
                email = f'{base_local}@{DOMAIN}'
            else:
                email = f'{base_local}{cnt}@{DOMAIN}'
            email_counts[base_local] = cnt + 1

            # full_name from hall
            full_name = f'Hall Manager {hall.code}'

            managers.append({
                'email': email,
                'full_name': full_name,
                'hall': hall,
                'phone': phone,
            })

        self.stdout.write(self.style.MIGRATE_HEADING('Assigning hall-wise access'))

        emails = []
        for spec in managers:
            # phone is unique in DB — if DEFAULT_PHONE already taken, generate sequential variant
            desired_phone = spec['phone']
            # ensure uniqueness: if phone exists for another user (not this email), suffix it
            base_phone_digits = desired_phone.lstrip('+')
            attempt_phone = desired_phone
            suffix = 0
            while User.objects.filter(phone=attempt_phone).exclude(email=spec['email']).exists():
                suffix += 1
                # generate variant: base + suffix (e.g. +8801670502283 -> +88016705022831)
                attempt_phone = f"{desired_phone}{suffix}"
                # trim to 15 digits + '+' if too long
                digits = attempt_phone.lstrip('+')
                if len(digits) > 15:
                    digits = digits[:15]
                    attempt_phone = f"+{digits}"
                if suffix > 20:
                    attempt_phone = None
                    break

            try:
                user, created = User.objects.update_or_create(
                    email=spec['email'],
                    defaults={'full_name': spec['full_name'], 'is_active': True, 'phone': attempt_phone},
                )
            except Exception as e:
                # fallback if phone still collides (race) — try without phone
                if 'phone' in str(e).lower() or 'unique' in str(e).lower():
                    user, created = User.objects.update_or_create(
                        email=spec['email'],
                        defaults={'full_name': spec['full_name'], 'is_active': True, 'phone': None},
                    )
                    attempt_phone = None
                else:
                    raise
            # ensure fields
            if attempt_phone is not None:
                user.phone = attempt_phone
            else:
                user.phone = None
            user.set_password(password)
            user.managed_hall = spec['hall']
            user.is_active = True
            user.save()
            emails.append(spec['email'])

            status = 'created' if created else 'updated'
            self.stdout.write(self.style.SUCCESS(
                f'{status:7} {spec["email"]:<28} -> {spec["hall"].code} ({spec["hall"].name}) phone={user.phone}'
            ))

        existing_superuser = User.objects.filter(is_superuser=True).exists()
        if existing_superuser:
            self.stdout.write(self.style.SUCCESS(
                'Superuser(s) already exist and keep global access to every hall.'
            ))
        else:
            self.stdout.write(self.style.WARNING(
                'No superuser found. Create one with `python manage.py createsuperuser` '
                'if you want global (all-hall) access.'
            ))

        self.stdout.write(self.style.SUCCESS(
            f'Done. Login: {", ".join(emails)} (password: {password} phone: {phone})'
        ))

    def _pick_default_codes(self):
        codes = list(Hall.objects.values_list('code', flat=True).exclude(code__isnull=True))
        if codes:
            return codes[:2]
        raise CommandError(
            'No halls with codes found. Run `python manage.py seed_hall` first or pass '
            '`--halls <code1> <code2> ...`.'
        )

    def _resolve_hall(self, code):
        normalized = (code or '').strip()
        hall = Hall.objects.filter(code__iexact=normalized).first()
        if hall is None:
            raise CommandError(f'Hall with code "{code}" does not exist. Run seed_hall first.')
        return hall
