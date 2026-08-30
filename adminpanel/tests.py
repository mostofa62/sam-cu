from io import StringIO

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.models import ADMIN_GROUP_NAME, User
from halls.models import Block, Floor, Hall, Room, Seat
from students.services import pull_students_from_external_system


def make_structure():
    hall = Hall.objects.create(name='Hall X', code='HX')
    block = Block.objects.create(hall=hall, name='Block A')
    floor = Floor.objects.create(hall=hall, block=block, name='Ground Floor')
    room = Room.objects.create(hall=hall, floor=floor, name='101', capacity=4)
    seat = Seat.objects.create(hall=hall, room=room, seat_number='1')
    return hall, block, floor, room, seat


class AdminPanelPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        if not Group.objects.filter(name=ADMIN_GROUP_NAME).exists():
            call_command('seed_admin', count=1, stdout=StringIO())
        cls.admin = User.objects.get(email='admin.one@example.com')
        cls.manager = User.objects.create_user(
            email='mgr@example.com', phone='+8801700000099', password='pw',
        )
        (cls.hall, cls.block, cls.floor,
         cls.room, cls.seat) = make_structure()

    def login_admin(self):
        self.client.force_login(self.admin)

    def test_every_list_page_renders_for_admin_group_member(self):
        self.login_admin()
        urls = [
            'adminpanel:index', 'adminpanel:hall_list', 'adminpanel:block_list',
            'adminpanel:floor_list', 'adminpanel:room_list', 'adminpanel:seat_list',
            'adminpanel:user_list', 'adminpanel:student_list',
            'adminpanel:call_list', 'adminpanel:assignment_list',
            'adminpanel:log_list', 'adminpanel:reason_list',
        ]
        for url_name in urls:
            with self.subTest(url=url_name):
                resp = self.client.get(reverse(url_name))
                self.assertEqual(resp.status_code, 200)

    def test_hall_crud_flow(self):
        self.login_admin()
        # create
        resp = self.client.post(reverse('adminpanel:hall_add'), {
            'name': 'Hall Y', 'code': 'HY', 'hall_type': 'M', 'minority': 'N',
            'color': '#6366f1', 'has_blocks': 'on', 'description': '',
        })
        self.assertRedirects(resp, reverse('adminpanel:hall_list'))
        hall_y = Hall.objects.get(code='HY')
        # update
        resp = self.client.post(reverse('adminpanel:hall_edit', args=[hall_y.pk]), {
            'name': 'Hall Y Renamed', 'code': 'HY', 'hall_type': 'M', 'minority': 'N',
            'color': '#6366f1',
        })
        self.assertRedirects(resp, reverse('adminpanel:hall_list'))
        hall_y.refresh_from_db()
        self.assertEqual(hall_y.name, 'Hall Y Renamed')
        # delete
        resp = self.client.post(reverse('adminpanel:hall_delete', args=[hall_y.pk]))
        self.assertRedirects(resp, reverse('adminpanel:hall_list'))
        self.assertFalse(Hall.objects.filter(code='HY').exists())

    def test_floor_rejects_block_from_other_hall(self):
        self.login_admin()
        other_hall = Hall.objects.create(name='Other', code='OZ')
        resp = self.client.post(reverse('adminpanel:floor_add'), {
            'hall': other_hall.pk, 'block': self.block.pk,
            'name': 'Broken Floor', 'color': '#f59e0b',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'belongs to a different hall')

    def test_manager_can_be_created_from_panel(self):
        self.login_admin()
        resp = self.client.post(reverse('adminpanel:user_add'), {
            'full_name': 'New Manager', 'email': 'nm@example.com',
            'phone': '+8801700000777', 'managed_hall': self.hall.pk,
            'is_active': 'on', 'password1': 'Str0ngPass!x', 'password2': 'Str0ngPass!x',
        })
        self.assertRedirects(resp, reverse('adminpanel:user_list'))
        manager = User.objects.get(email='nm@example.com')
        self.assertEqual(manager.managed_hall, self.hall)
        self.assertFalse(manager.is_superuser)
        self.assertTrue(manager.check_password('Str0ngPass!x'))

    def test_superuser_cannot_be_deleted_from_panel(self):
        self.login_admin()
        root = User.objects.create_superuser(
            email='root@example.com', phone='+8801700000000', password='pw')
        resp = self.client.post(reverse('adminpanel:user_delete', args=[root.pk]), follow=True)
        self.assertRedirects(resp, reverse('adminpanel:user_list'))
        self.assertTrue(User.objects.filter(pk=root.pk).exists())

    def test_student_pull_upserts_master_data(self):
        created, updated = pull_students_from_external_system(source=[
            {'student_id': 'S-1', 'name_en': 'Alpha'},
            {'student_id': 'S-2', 'name_en': 'Beta'},
        ])
        self.assertEqual((created, updated), (2, 0))
        # Second pull refreshes existing rows and adds nothing new.
        created, updated = pull_students_from_external_system(source=[
            {'student_id': 'S-1', 'name_en': 'Alpha Prime'},
            {'student_id': 'S-3', 'name_en': 'Gamma'},
        ])
        self.assertEqual((created, updated), (1, 1))
        from students.models import Student
        self.assertEqual(Student.objects.get(student_id='S-1').name_en, 'Alpha Prime')

    def test_student_pull_view_reports_counts(self):
        self.login_admin()
        resp = self.client.post(reverse('adminpanel:student_pull'), follow=True)
        messages = [str(m) for m in resp.context['messages']]
        self.assertTrue(any('Pull complete' in m for m in messages))

    def test_release_reason_crud(self):
        self.login_admin()
        resp = self.client.post(reverse('adminpanel:reason_add'), {
            'name': 'Left the hall', 'is_active': 'on', 'sort_order': 5,
        })
        self.assertRedirects(resp, reverse('adminpanel:reason_list'))
        from allocations.models import SeatReleaseReason
        reason = SeatReleaseReason.objects.get(name='Left the hall')
        resp = self.client.post(reverse('adminpanel:reason_delete', args=[reason.pk]))
        self.assertRedirects(resp, reverse('adminpanel:reason_list'))
        self.assertFalse(SeatReleaseReason.objects.filter(pk=reason.pk).exists())
