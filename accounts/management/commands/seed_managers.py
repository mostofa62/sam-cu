from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import User
from halls.models import Hall

DEFAULT_PASSWORD = 'SamHallManager@202609'


class Command(BaseCommand):
    help = (
        'Create demo hall managers and assign their single hall. A user manages at most one '
        'hall, but a hall can have many managers. Managers are generated from the halls that '
        'are passed: every hall gets one manager, and each hall after the first also gets a '
        'second (shared) manager.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--halls', nargs='+', default=None,
            help='Hall codes to assign managers to. Case-insensitive; e.g. HALALA == halala. When omitted the first two available are used.',
        )
        parser.add_argument(
            '--password', default=DEFAULT_PASSWORD,
            help=f'Password for every created manager (default: {DEFAULT_PASSWORD}).',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        codes = options['halls'] or self._pick_default_codes()
        password = options['password']

        halls = [self._resolve_hall(code) for code in codes]
        if not halls:
            raise CommandError('At least one hall is required for the demo scenario.')

        managers = []
        for i, hall in enumerate(halls):
            letter = chr(ord('a') + i)
            managers.append({
                'email': f'manager.{letter}@cu.ac.bd',
                'full_name': f'Hall Manager {letter.upper()}',
                'hall': hall,
            })
            if i > 0:
                # Second manager on the same hall to demonstrate the
                # "multiple users can manage one hall" rule.
                managers.append({
                    'email': f'manager.{letter}1@cu.ac.bd',
                    'full_name': f'Hall Manager {letter.upper()} (2nd)',
                    'hall': hall,
                })

        self.stdout.write(self.style.MIGRATE_HEADING('Assigning hall-wise access'))

        emails = []
        for spec in managers:
            user, created = User.objects.update_or_create(
                email=spec['email'],
                defaults={'full_name': spec['full_name'], 'is_active': True},
            )
            user.set_password(password)
            user.managed_hall = spec['hall']
            user.save()
            emails.append(spec['email'])

            status = 'created' if created else 'updated'
            self.stdout.write(self.style.SUCCESS(
                f'{status:7} {spec["email"]:<28} -> {spec["hall"].name}'
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
            f'Done. Login: {", ".join(emails)} (password: {password})'
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