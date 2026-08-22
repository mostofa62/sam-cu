from django.test import TestCase, override_settings
from django.urls import clear_script_prefix, set_script_prefix

from accounts.models import User
from allocations.models import OrderChoices, SeatAssignment
from halls.models import Block, Floor, Hall, Room, Seat

SUB_PATH = override_settings(
    FORCE_SCRIPT_NAME='/sam',
    STATIC_URL='/sam/static/',
    MEDIA_URL='/sam/media/',
)


def make_hall(name='Hall X', code='HX'):
    hall = Hall.objects.create(name=name, code=code)
    block = Block.objects.create(hall=hall, name='Block A')
    floor = Floor.objects.create(hall=hall, block=block, name='Ground Floor')
    room = Room.objects.create(hall=hall, floor=floor, name='101')
    seat = Seat.objects.create(hall=hall, room=room, seat_number='1')
    return hall, seat


@SUB_PATH
class SubPathServeTests(TestCase):
    def setUp(self):
        self.hall_x, _ = make_hall('Hall X', 'HX')
        # The test Client does not run WSGI_.__call__, so replicate what the
        # WSGIHandler does with FORCE_SCRIPT_NAME: make /sam the thread prefix.
        set_script_prefix('/sam')
        # Requests arrive with the /sam prefix ALREADY stripped by the proxy,
        # exactly like Traefik's stripprefix middleware sends them to Django.
        self.dash = '/'
        self.user = User.objects.create_user(email='a@example.com', phone='+8801700000001', password='pw', is_staff=True)
        self.user.managed_hall = self.hall_x
        self.user.save()
        self.client.login(email='a@example.com', password='pw')

    def tearDown(self):
        # Restore the thread-local script prefix so other tests keep resolving
        # URLs without /sam (the subpath is only forced in this test class).
        clear_script_prefix()

    def test_pages_render_at_stripped_path_with_prefix_urls(self):
        resp = self.client.get(self.dash)
        self.assertEqual(resp.status_code, 200)
        # Links must carry the /sam prefix...
        self.assertContains(resp, '/sam/allocations/assignments/')
        self.assertContains(resp, '/sam/allocations/revoke/')
        self.assertContains(resp, '/sam/admin/')
        # ...and static assets must too.
        self.assertContains(resp, '/sam/static/')

    def test_logout_form_action_prefixed(self):
        resp = self.client.get(self.dash)
        self.assertContains(resp, 'action="/sam/accounts/logout/"')

    def test_active_assignments_page_prefixed(self):
        SeatAssignment.objects.create(seat=Seat.objects.filter(hall=self.hall_x).first(),
                                      student_id='STU-1', order=OrderChoices.PRIMARY, is_active=True)
        resp = self.client.get('/allocations/assignments/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '/sam/allocations/assign/')
        self.assertContains(resp, 'action="/sam/allocations/assignments/%d/revoke/"' % (
            SeatAssignment.objects.get(student_id='STU-1').pk,
        ))

    def test_assign_page_json_fetch_urls_prefixed(self):
        resp = self.client.get('/allocations/assign/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'const roomsJsonUrl = "/sam/allocations/rooms-json/";')
        self.assertContains(resp, 'const roomSeatsJsonUrl = "/sam/allocations/room-seats.json";')