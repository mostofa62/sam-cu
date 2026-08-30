from io import StringIO

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.models import ADMIN_GROUP_NAME, User
from halls.models import Hall


class SeedAdminCommandTests(TestCase):
    def _run(self, **kwargs):
        out = StringIO()
        call_command('seed_admin', stdout=out, **kwargs)
        return out.getvalue()

    def test_creates_group_with_two_demo_admins(self):
        output = self._run()
        group = Group.objects.get(name=ADMIN_GROUP_NAME)
        self.assertEqual(group.permissions.count(), 48)
        admins = User.objects.filter(groups__name=ADMIN_GROUP_NAME)
        self.assertEqual(admins.count(), 2)
        for admin in admins:
            self.assertTrue(admin.is_staff)
            self.assertFalse(admin.is_superuser)
            self.assertIsNone(admin.managed_hall_id)
            self.assertTrue(admin.is_app_admin)
        self.assertIn('admin.one@example.com', output)

    def test_is_rerunnable_and_never_grants_superuser(self):
        self._run()
        self._run(password='NewPass!123')
        self.assertEqual(User.objects.filter(groups__name=ADMIN_GROUP_NAME).count(), 2)
        admin = User.objects.get(email='admin.one@example.com')
        self.assertTrue(admin.check_password('NewPass!123'))
        self.assertFalse(admin.is_superuser)

    def test_count_option(self):
        self._run(count=1)
        self.assertEqual(User.objects.filter(groups__name=ADMIN_GROUP_NAME).count(), 1)


class AppAdminRoleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name=ADMIN_GROUP_NAME)
        cls.hall_a = Hall.objects.create(name='Hall A', code='HA')
        cls.hall_b = Hall.objects.create(name='Hall B', code='HB')

    def make_user(self, email, **fields):
        return User.objects.create_user(
            email=email, phone='+8801700000099', password='pw', **fields,
        )

    def test_admin_group_member_sees_every_hall_without_superuser(self):
        user = self.make_user('grp@example.com', is_staff=True)
        user.groups.add(Group.objects.get(name=ADMIN_GROUP_NAME))
        self.assertTrue(user.in_admin_group)
        self.assertTrue(user.is_app_admin)
        self.assertFalse(user.is_superuser)
        self.assertCountEqual(user.visible_halls(), [self.hall_a, self.hall_b])

    def test_plain_manager_sees_only_managed_hall(self):
        user = self.make_user('mgr@example.com')
        user.managed_hall = self.hall_a
        user.save()
        self.assertFalse(user.is_app_admin)
        self.assertCountEqual(user.visible_halls(), [self.hall_a])


class AdminPanelAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        if not Group.objects.filter(name=ADMIN_GROUP_NAME).exists():
            call_command('seed_admin', count=1, stdout=StringIO())
        cls.admin = User.objects.get(email='admin.one@example.com')
        cls.manager = User.objects.create_user(
            email='mgr@example.com', phone='+8801700000099', password='pw',
        )

    def login(self, user):
        self.client.force_login(user)

    def test_admin_panel_overview_allowed_for_group_admin(self):
        self.login(self.admin)
        resp = self.client.get(reverse('adminpanel:index'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Administration')

    def test_admin_panel_denied_for_hall_manager(self):
        self.login(self.manager)
        resp = self.client.get(reverse('adminpanel:index'), follow=True)
        self.assertRedirects(resp, reverse('dashboard:home'))

    def test_admin_panel_requires_login(self):
        resp = self.client.get(reverse('adminpanel:hall_list'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('accounts/login', resp.url)

    def test_django_admin_rejects_non_superuser(self):
        """The Django admin at /admin/ must stay superuser-only."""
        from hsm.admin_site import hsm_admin_site
        self.login(self.admin)
        request = self.client.get('/admin/').wsgi_request
        self.assertFalse(hsm_admin_site.has_permission(request))
        superuser = User.objects.create_superuser(
            email='root@example.com', phone='+8801700000000', password='pw',
        )
        self.client.force_login(superuser)
        request = self.client.get('/admin/').wsgi_request
        self.assertTrue(hsm_admin_site.has_permission(request))

    def test_sidebar_hides_super_admin_link_from_group_admin(self):
        self.login(self.admin)
        resp = self.client.get(reverse('adminpanel:index'))
        # The Admin-group administrator gets the Administration menu...
        self.assertContains(resp, 'Halls &amp; Seats')
        # ...but never the super-admin (Django admin) visit link.
        self.assertNotContains(resp, 'Super Admin Panel')

    def test_sidebar_shows_super_admin_link_to_superuser(self):
        root = User.objects.create_superuser(
            email='root@example.com', phone='+8801700000000', password='pw',
        )
        self.login(root)
        resp = self.client.get(reverse('dashboard:home'))
        self.assertContains(resp, 'Super Admin Panel')
