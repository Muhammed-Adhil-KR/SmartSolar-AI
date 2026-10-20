from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class StaffBounceTests(TestCase):
    def setUp(self):
        User.objects.create_superuser('root', 'r@x.com', 'pw')
        self.client.login(username='root', password='pw')

    def test_customer_pages_send_staff_to_admin_panel(self):
        for name in ('dashboard:home', 'solar:appliance_list', 'solar:setup_system',
                     'solar:setup_location', 'solar:edit_system',
                     'forecast:prediction_history', 'decision_support:current'):
            resp = self.client.get(reverse(name))
            self.assertRedirects(resp, reverse('adminpanel:overview'), fetch_redirect_response=False,
                                 msg_prefix=name)

    def test_staff_never_lands_on_setup_steps(self):
        resp = self.client.get(reverse('dashboard:home'))
        self.assertNotIn('setup', resp.url)

    def test_staff_login_lands_on_admin_panel(self):
        self.client.logout()
        resp = self.client.post(reverse('accounts:login'),
                                {'username': 'root', 'password': 'pw'}, follow=True)
        self.assertEqual(resp.redirect_chain[-1][0], reverse('adminpanel:overview'))

    def test_customer_still_goes_through_setup(self):
        self.client.logout()
        User.objects.create_user('asha', password='pw')
        self.client.login(username='asha', password='pw')
        resp = self.client.get(reverse('dashboard:home'))
        self.assertRedirects(resp, reverse('solar:setup_system'), fetch_redirect_response=False)

    def test_customer_can_still_open_solar_pages(self):
        self.client.logout()
        User.objects.create_user('asha', password='pw')
        self.client.login(username='asha', password='pw')
        self.assertEqual(self.client.get(reverse('solar:setup_system')).status_code, 200)

    def test_anonymous_is_still_sent_to_login(self):
        self.client.logout()
        resp = self.client.get(reverse('solar:appliance_list'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp.url)