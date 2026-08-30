from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import ADMIN_GROUP_NAME, User
from allocations.models import (AllocationCall, HallAllocation, SeatAssignment,
                                SeatAssignmentLog, SeatMaintenance,
                                SeatReleaseReason)
from halls.models import Block, Floor, Hall, Room, Seat
from students.models import Student

DEFAULT_PASSWORD = 'HallAdmin!2024'

# Everything a non-superuser administrator needs: full CRUD on the hall
# structure and students, manager accounts, allocation calls plus read access
# to assignments / audit logs. Django admin itself stays superuser-only.
MANAGED_MODELS = (
    Hall, Block, Floor, Room, Seat,
    Student,
    AllocationCall, HallAllocation,
    SeatReleaseReason, SeatAssignment, SeatAssignmentLog, SeatMaintenance,
)

DEMO_ADMINS = [
    {'email': 'admin.one@example.com', 'full_name': 'Admin One', 'phone': '+8801700000001'},
    {'email': 'admin.two@example.com', 'full_name': 'Admin Two', 'phone': '+8801700000002'},
]


class Command(BaseCommand):
    help = (
        'Create the "Admin" group — a full administrator role WITHOUT superuser rights '
        '(manages halls/blocks/floors/rooms/seats, hall managers, allocation calls, '
        'students and sees assignment logs) — and seed two demo admin accounts for it.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--password', default=DEFAULT_PASSWORD,
            help=f'Password for every created demo admin (default: {DEFAULT_PASSWORD}).',
        )
        parser.add_argument(
            '--count', type=int, default=2, choices=(1, 2),
            help='How many demo admins to create (default: 2).',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        password = options['password']

        group = self._ensure_group()

        self.stdout.write(self.style.MIGRATE_HEADING('Creating demo administrators'))

        created_any = False
        for spec in DEMO_ADMINS[:options['count']]:
            user, created = User.objects.get_or_create(
                email=spec['email'],
                defaults={
                    'full_name': spec['full_name'],
                    'phone': spec['phone'],
                    'is_active': True,
                    'is_staff': True,
                    'is_superuser': False,
                },
            )
            user.is_active = True
            user.is_staff = True      # shows up as staff; /admin/ still blocks them
            user.is_superuser = False # never a superuser — that is the point of this role
            user.managed_hall = None  # global scope, not tied to one hall
            user.set_password(password)
            user.save()
            user.groups.add(group)
            created_any |= created
            status = 'created' if created else 'updated'
            self.stdout.write(self.style.SUCCESS(
                f'{status:7} {user.email:<28} [{ADMIN_GROUP_NAME}] {user.full_name}'
            ))

        self.stdout.write('')
        self.stdout.write(self.style.WARNING(
            'These admins manage everything from the in-app panel at /manage/ '
            '(Administration menu). They can never open the Django admin at /admin/ — '
            'that stays superuser-only.'
        ))
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Done. Login with any seeded admin email (password: {password})'
            + ('' if created_any else '  [accounts already existed — password reset to default]')
        ))

    def _ensure_group(self):
        """Create/update the Admin group with all model permissions it needs."""
        group, _ = Group.objects.get_or_create(name=ADMIN_GROUP_NAME)
        wanted = set()
        for model in MANAGED_MODELS:
            for action in ('add', 'change', 'delete', 'view'):
                codename = f'{action}_{model._meta.model_name}'
                wanted.add((model._meta.app_label, codename))
        perms = Permission.objects.filter(
            content_type__app_label__in={app for app, _ in wanted},
        )
        perms = [p for p in perms if (p.content_type.app_label, p.codename) in wanted]
        group.permissions.set(perms)
        self.stdout.write(self.style.SUCCESS(
            f'Group "{ADMIN_GROUP_NAME}" ready with {len(perms)} permissions '
            f'(halls, students, users, allocations).'
        ))
        return group
