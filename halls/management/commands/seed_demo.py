from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import User
from allocations.models import (ActionChoices, OrderChoices, SeatAssignment,
                                SeatAssignmentLog, SeatMaintenance)
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
    help = 'Seed demo data: real CU halls, demo blocks/floors/rooms/seats, sample assignments and maintenance.'

    def handle(self, *args, **options):
        self._wipe_demo_data()

        admin = User.objects.filter(is_superuser=True).first()

        halls = []
        for i, (code, name, hall_type, minority) in enumerate(HALL_DATA):
            hall = Hall.objects.create(
                name=name,
                code=code,
                hall_type=hall_type,
                minority=minority,
                color=COLORS[i % len(COLORS)],
                has_blocks=True,
            )
            halls.append(hall)

        self.stdout.write(self.style.SUCCESS(f'Created {len(halls)} halls.'))

        # Demo structure: 2 blocks, 1 floor each, 2 rooms, 4 seats each per hall
        for hall in halls:
            block_a = Block.objects.create(hall=hall, name='Block A', color='#0ea5e9')
            block_b = Block.objects.create(hall=hall, name='Block B', color='#14b8a6')
            rooms_spec = [
                ('Ground Floor', block_a, 101),
                ('1st Floor', block_b, 201),
            ]
            for fname, block, base in rooms_spec:
                floor = Floor.objects.create(hall=hall, block=block, name=fname, color=hall.color)
                for offset in range(2):
                    room = Room.objects.create(
                        hall=hall, floor=floor, name=str(base + offset), capacity=4, color=hall.color,
                    )
                    for seat_no in range(1, 5):
                        Seat.objects.create(hall=hall, room=room, seat_number=str(seat_no))

        self.stdout.write(self.style.SUCCESS('Blocks, floors, rooms and seats created.'))

        # Sample assignments across the first two halls (seat sharing demo)
        sample_halls = halls[:2]
        seats = list(Seat.objects.filter(hall__in=sample_halls).order_by('room__floor', 'room', 'seat_number'))
        sample = [
            ('2101CSE001', seats[0], OrderChoices.PRIMARY),
            ('2101CSE002', seats[0], OrderChoices.SECONDARY),  # shared seat
            ('2101EEE005', seats[1], OrderChoices.PRIMARY),
            ('2101BBA012', seats[2], OrderChoices.PRIMARY),
            ('2101PHY003', seats[3], OrderChoices.PRIMARY),
            ('2101CSE033', seats[4], OrderChoices.PRIMARY),
            ('2101ENG007', seats[5], OrderChoices.PRIMARY),
            ('2101MTH002', seats[6], OrderChoices.PRIMARY),
        ]
        for sid, seat, order in sample:
            assignment = SeatAssignment.objects.create(
                seat=seat, student_id=sid, order=order, is_active=True,
            )
            SeatAssignmentLog.objects.create(
                student_id=sid, seat=seat, order=order,
                action=ActionChoices.ASSIGNED,
                note='Seed data.', performed_by=admin,
            )

        self.stdout.write(self.style.SUCCESS('Sample assignments created.'))

        m_seat = Seat.objects.filter(hall__in=sample_halls).exclude(assignments__is_active=True).first()
        if m_seat:
            SeatMaintenance.objects.create(seat=m_seat, reason='Renovation work', note='Seat cushion replacement.')
            self.stdout.write(self.style.SUCCESS('Maintenance record created.'))

        self.stdout.write(self.style.SUCCESS('Demo data seeding complete.'))

    def _wipe_demo_data(self):
        SeatAssignmentLog.objects.all().delete()
        SeatMaintenance.objects.all().delete()
        SeatAssignment.objects.all().delete()
        Seat.objects.all().delete()
        Room.objects.all().delete()
        Floor.objects.all().delete()
        Block.objects.all().delete()
        Hall.objects.all().delete()
