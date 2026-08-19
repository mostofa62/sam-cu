from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from allocations.models import OrderChoices, SeatAssignment, SeatMaintenance
from halls.models import Block, Floor, Hall, Room, Seat


def make_hall(name='Hall X', code='HX'):
    hall = Hall.objects.create(name=name, code=code)
    block = Block.objects.create(hall=hall, name='Block A')
    floor = Floor.objects.create(hall=hall, block=block, name='Ground Floor')
    room_a = Room.objects.create(hall=hall, floor=floor, name='101')
    room_b = Room.objects.create(hall=hall, floor=floor, name='102')
    s1 = Seat.objects.create(hall=hall, room=room_a, seat_number='1')
    s2 = Seat.objects.create(hall=hall, room=room_a, seat_number='2')
    s3 = Seat.objects.create(hall=hall, room=room_b, seat_number='1')
    return hall, [s1, s2, s3]


class VisibleHallsTests(TestCase):
    def setUp(self):
        self.hall_x, _ = make_hall('Hall X', 'HX')
        self.hall_y, _ = make_hall('Hall Y', 'HY')
        self.superuser = User.objects.create_superuser(email='root@example.com', phone='+8801700000000', password='pw')
        self.manager_a = User.objects.create_user(email='a@example.com', phone='+8801700000001', password='pw')
        self.manager_a.managed_hall = self.hall_x
        self.manager_a.save()
        self.manager_b = User.objects.create_user(email='b@example.com', phone='+8801700000002', password='pw')
        self.manager_b.managed_hall = self.hall_y
        self.manager_b.save()

    def test_superuser_sees_every_hall(self):
        self.assertEqual(set(self.superuser.visible_halls()), {self.hall_x, self.hall_y})

    def test_manager_sees_only_own_hall(self):
        self.assertEqual(set(self.manager_a.visible_halls()), {self.hall_x})
        self.assertEqual(set(self.manager_b.visible_halls()), {self.hall_y})

    def test_manager_cannot_access_another_hall(self):
        self.assertNotIn(self.hall_y, self.manager_a.visible_halls())
        self.assertNotIn(self.hall_x, self.manager_b.visible_halls())

    def test_is_hall_manager_flag(self):
        self.assertTrue(self.manager_a.is_hall_manager)
        empty = User.objects.create_user(email='empty@example.com', phone='+8801700000009', password='pw')
        self.assertFalse(empty.is_hall_manager)


class DashboardScopingTests(TestCase):
    def setUp(self):
        self.hall_x, seats_x = make_hall('Hall X', 'HX')
        self.hall_y, seats_y = make_hall('Hall Y', 'HY')
        self.user = User.objects.create_user(email='a@example.com', phone='+8801700000001', password='pw')
        self.user.managed_hall = self.hall_x
        self.user.save()
        self.client.login(email='a@example.com', password='pw')

    def test_dashboard_stats_scoped_to_managed_halls(self):
        # An assignment in the OTHER hall must not leak into this manager's stats.
        SeatAssignment.objects.create(seat=Seat.objects.filter(hall=self.hall_y).first(),
                                      student_id='STU-OTHER', order=OrderChoices.PRIMARY, is_active=True)
        resp = self.client.get(reverse('dashboard:home'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['total_halls'], 1)
        self.assertEqual(resp.context['occupied_seats'], 0)
        self.assertContains(resp, 'Hall X')
        self.assertNotContains(resp, 'Hall Y')

    def test_dashboard_maintenance_only_shows_managed_halls(self):
        # A maintenance record in a hall the manager does NOT manage must not appear
        # in the "Seats On Hold" list, while one inside the managed hall does.
        SeatMaintenance.objects.create(seat=Seat.objects.filter(hall=self.hall_x).first(),
                                       reason='Own hall repair', is_active=True)
        SeatMaintenance.objects.create(seat=Seat.objects.filter(hall=self.hall_y).first(),
                                       reason='Other hall repair', is_active=True)
        resp = self.client.get(reverse('dashboard:home'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['under_maintenance'], 1)
        self.assertContains(resp, 'Own hall repair')
        self.assertNotContains(resp, 'Other hall repair')


class AssignScopingTests(TestCase):
    def setUp(self):
        self.hall_x, seats_x = make_hall('Hall X', 'HX')
        self.hall_y, seats_y = make_hall('Hall Y', 'HY')
        self.user = User.objects.create_user(email='a@example.com', phone='+8801700000001', password='pw')
        self.user.managed_hall = self.hall_x
        self.user.save()
        self.client.login(email='a@example.com', password='pw')

    def test_assign_page_only_lists_managed_halls(self):
        resp = self.client.get(reverse('allocations:assign'))
        self.assertEqual(resp.status_code, 200)
        form = resp.context['form']
        self.assertEqual(set(form.fields['hall'].queryset), {self.hall_x})

    def test_single_hall_manager_gets_hidden_hall_preset(self):
        # Manager of exactly one hall must not have to pick the hall — it is
        # pre-set (hidden input) and rooms are rendered server-side immediately.
        resp = self.client.get(reverse('allocations:assign'))
        form = resp.context['form']
        self.assertEqual(form.single_hall, self.hall_x)
        self.assertEqual(form.fields['hall'].widget.input_type, 'hidden')
        self.assertEqual(set(form.fields['room'].queryset),
                         set(Room.objects.filter(hall=self.hall_x)))
        # The hall select is rendered as a hidden, pre-set input (no visible picker).
        self.assertContains(resp, 'id="id_hall"')
        self.assertContains(resp, 'type="hidden"')
        # Room labels must not repeat the hall name (it is already shown/preset).
        self.assertContains(resp, 'Block A / Ground Floor - Room 101')
        self.assertNotContains(resp, 'Hall X - Block A')

    def test_superuser_keeps_hall_selector(self):
        # Superusers manage no single hall, so they keep the full hall picker.
        superuser = User.objects.create_superuser(email='root@example.com', phone='+8801700000000', password='pw')
        self.client.login(email='root@example.com', password='pw')
        resp = self.client.get(reverse('allocations:assign'))
        form = resp.context['form']
        self.assertIsNone(form.single_hall)
        self.assertEqual(set(form.fields['hall'].queryset), {self.hall_x, self.hall_y})
        self.assertNotEqual(form.fields['hall'].widget.input_type, 'hidden')

    def test_user_without_hall_gets_no_hall_choices(self):
        no_hall = User.objects.create_user(email='plain@example.com', phone='+8801700000003', password='pw')
        self.client.login(email='plain@example.com', password='pw')
        resp = self.client.get(reverse('allocations:assign'))
        form = resp.context['form']
        self.assertIsNone(form.single_hall)
        self.assertEqual(set(form.fields['hall'].queryset), set())

    def test_single_hall_manager_can_still_assign(self):
        seat_x = Seat.objects.filter(hall=self.hall_x).first()
        resp = self.client.post(reverse('allocations:assign'), {
            'student_id': 'STU-SINGLE',
            'hall': self.hall_x.id,
            'room': seat_x.room_id,
            'seat': seat_x.id,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(SeatAssignment.objects.filter(student_id='STU-SINGLE').exists())

    def test_cannot_assign_seat_outside_managed_halls(self):
        seat_y = Seat.objects.filter(hall=self.hall_y).first()
        resp = self.client.post(reverse('allocations:assign'), {
            'student_id': 'STU-1',
            'hall': self.hall_y.id,
            'room': seat_y.room_id,
            'seat': seat_y.id,
        })
        # Redirect only on success; on failure the form re-renders with errors.
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(SeatAssignment.objects.filter(student_id='STU-1').exists())

    def test_can_assign_seat_inside_managed_halls(self):
        seat_x = Seat.objects.filter(hall=self.hall_x).first()
        resp = self.client.post(reverse('allocations:assign'), {
            'student_id': 'STU-1',
            'hall': self.hall_x.id,
            'room': seat_x.room_id,
            'seat': seat_x.id,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(SeatAssignment.objects.filter(student_id='STU-1', seat__hall=self.hall_x).exists())

    def test_assign_student_with_existing_active_seat_renders_error_not_crash(self):
        # Regression: SeatAssignment.full_clean() raises a dict-based ValidationError;
        # it must be surfaced to the form as a plain message, not crash with
        # "field must be None when error is a dictionary".
        seat_x_1 = Seat.objects.filter(hall=self.hall_x)[0]
        seat_x_2 = Seat.objects.filter(hall=self.hall_x)[1]
        SeatAssignment.objects.create(seat=seat_x_1, student_id='STU-EXIST',
                                      order=OrderChoices.PRIMARY, is_active=True)
        resp = self.client.post(reverse('allocations:assign'), {
            'student_id': 'STU-EXIST',
            'hall': self.hall_x.id,
            'room': seat_x_2.room_id,
            'seat': seat_x_2.id,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'already has an active seat assigned')
        # The message must name the student's existing seat location (hall/block/floor/room/seat).
        self.assertContains(resp, 'Hall X - Block A / Ground Floor - Room 101 - Seat 1')
        # The seat is in the manager's own hall, so a release hint is appropriate.
        self.assertContains(resp, 'Release it from the Active Assignments page')
        self.assertFalse(SeatAssignment.objects.filter(student_id='STU-EXIST', seat=seat_x_2).exists())

    def test_seat_labels_always_short(self):
        # Seat options stay compact ('101 / Seat 1') both on first load and
        # after a failed submit — no hall/block/floor expansion either way.
        seat_y = Seat.objects.filter(hall=self.hall_y).first()
        room = Room.objects.filter(hall=self.hall_y).first()
        resp = self.client.get(reverse('allocations:assign'))
        self.assertEqual(resp.status_code, 200)
        form = resp.context['form']
        self.assertEqual(form.fields['seat'].label_from_instance(seat_y), '101 / Seat 1')
        resp = self.client.post(reverse('allocations:assign'), {
            'student_id': 'STU-1',
            'hall': self.hall_y.id,
            'room': room.id,
            'seat': seat_y.id,
        })
        self.assertEqual(resp.status_code, 200)
        form = resp.context['form']
        self.assertEqual(form.fields['seat'].label_from_instance(seat_y), '101 / Seat 1')
        self.assertNotContains(resp, 'Hall Y - Block A / Ground Floor - Room 101 - Seat 1')

    def test_existing_seat_in_another_hall_shows_facts_and_contact_not_release(self):
        # A manager who does NOT own the student's current hall must not be told
        # to release that seat — only the facts plus a pointer to that hall.
        seat_x = Seat.objects.filter(hall=self.hall_x)[0]
        seat_y = Seat.objects.filter(hall=self.hall_y)[0]
        SeatAssignment.objects.create(seat=seat_y, student_id='STU-Y',
                                      order=OrderChoices.PRIMARY, is_active=True)
        resp = self.client.post(reverse('allocations:assign'), {
            'student_id': 'STU-Y',
            'hall': self.hall_x.id,
            'room': seat_x.room_id,
            'seat': seat_x.id,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'already has an active seat assigned')
        self.assertContains(resp, 'Hall Y - Block A / Ground Floor - Room 101 - Seat 1')
        self.assertContains(resp, 'allotted')
        self.assertContains(resp, 'contact the manager of Hall Y')
        self.assertNotContains(resp, 'Release it')


class AssignmentsScopingTests(TestCase):
    def setUp(self):
        self.hall_x, self.seats_x = make_hall('Hall X', 'HX')
        self.hall_y, seats_y = make_hall('Hall Y', 'HY')
        self.user = User.objects.create_user(email='a@example.com', phone='+8801700000001', password='pw')
        self.user.managed_hall = self.hall_x
        self.user.save()
        self.client.login(email='a@example.com', password='pw')

    def test_active_assignments_only_shows_managed_halls(self):
        SeatAssignment.objects.create(seat=self.seats_x[0], student_id='IN-X', order=OrderChoices.PRIMARY, is_active=True)
        SeatAssignment.objects.create(seat=Seat.objects.filter(hall=self.hall_y).first(),
                                      student_id='IN-Y', order=OrderChoices.PRIMARY, is_active=True)
        resp = self.client.get(reverse('allocations:active_assignments'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'IN-X')
        self.assertNotContains(resp, 'IN-Y')

    def test_revoke_assignment_outside_managed_halls_is_ignored(self):
        assignment_y = SeatAssignment.objects.create(
            seat=Seat.objects.filter(hall=self.hall_y).first(),
            student_id='STU-Y', order=OrderChoices.PRIMARY, is_active=True,
        )
        resp = self.client.post(reverse('allocations:revoke_assignment', args=[assignment_y.pk]))
        self.assertEqual(resp.status_code, 302)
        assignment_y.refresh_from_db()
        self.assertTrue(assignment_y.is_active)

    def test_rooms_json_scoped(self):
        resp = self.client.get(reverse('allocations:rooms_json'), {'hall_id': self.hall_y.id})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['rooms'], [])

    def test_rooms_json_uses_compact_label(self):
        resp = self.client.get(reverse('allocations:rooms_json'), {'hall_id': self.hall_x.id})
        self.assertEqual(resp.status_code, 200)
        labels = [room['label'] for room in resp.json()['rooms']]
        self.assertTrue(labels)
        self.assertTrue(all('Hall X' not in label for label in labels))
        self.assertIn('Block A / Ground Floor - Room 101', labels)

    def test_room_seats_json_scoped(self):
        room_y = Room.objects.filter(hall=self.hall_y).first()
        resp = self.client.get(reverse('allocations:room_seats_json'), {'room_id': room_y.id})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['seats'], [])


class RevokeScopingTests(TestCase):
    def setUp(self):
        self.hall_x, _ = make_hall('Hall X', 'HX')
        self.hall_y, seats_y = make_hall('Hall Y', 'HY')
        self.user = User.objects.create_user(email='a@example.com', phone='+8801700000001', password='pw')
        self.user.managed_hall = self.hall_x
        self.user.save()
        self.client.login(email='a@example.com', password='pw')

    def test_revoke_bulk_form_only_releases_halls_in_scope(self):
        # Student sits only in hall Y (NOT managed). Revoking from the manager's scope
        # must report "belongs to another hall" and leave the assignment untouched.
        SeatAssignment.objects.create(seat=Seat.objects.filter(hall=self.hall_y).first(),
                                      student_id='STU-Y', order=OrderChoices.PRIMARY, is_active=True)
        resp = self.client.post(reverse('allocations:revoke'), {'student_id': 'STU-Y'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'belongs to another hall')
        self.assertNotContains(resp, 'No active seat assignment found')
        self.assertTrue(SeatAssignment.objects.filter(student_id='STU-Y', is_active=True).exists())

    def test_revoke_other_hall_student_message_has_full_details(self):
        # Real-id scenario: a manager tries to release a student whose active seat
        # is in a hall they do not manage. The form must show where the seat is.
        SeatAssignment.objects.create(seat=Seat.objects.filter(hall=self.hall_y).first(),
                                      student_id='20404053', order=OrderChoices.PRIMARY, is_active=True)
        resp = self.client.post(reverse('allocations:revoke'), {'student_id': '20404053'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '20404053')
        self.assertContains(resp, 'Hall Y - Block A / Ground Floor - Room 101 - Seat 1')
        self.assertContains(resp, 'belongs to another hall')
        self.assertContains(resp, 'only the manager of Hall Y can')
        self.assertTrue(SeatAssignment.objects.filter(student_id='20404053', is_active=True).exists())

    def test_revoke_own_hall_student_can_still_release(self):
        SeatAssignment.objects.create(seat=Seat.objects.filter(hall=self.hall_x).first(),
                                      student_id='19105036', order=OrderChoices.PRIMARY, is_active=True)
        resp = self.client.post(reverse('allocations:revoke'), {'student_id': '19105036'})
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(SeatAssignment.objects.filter(student_id='19105036', is_active=True).exists())

    def test_revoke_service_scoped_to_halls(self):
        from .services import revoke_seat
        SeatAssignment.objects.create(seat=Seat.objects.filter(hall=self.hall_y).first(),
                                      student_id='STU-Y', order=OrderChoices.PRIMARY, is_active=True)
        with self.assertRaises(ValidationError):
            revoke_seat('STU-Y', halls=Hall.objects.filter(pk=self.hall_x.pk))
        self.assertTrue(SeatAssignment.objects.filter(student_id='STU-Y', is_active=True).exists())