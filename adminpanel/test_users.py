from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from forecast.models import Prediction
from solar.models import Appliance, SolarSystem


def make_customer(name, email='', first='', last='', active=True, system=False):
    user = User.objects.create_user(name, email=email, password='pw', first_name=first,
                                    last_name=last, is_active=active)
    if system:
        SolarSystem.objects.create(user=user, system_type=SolarSystem.ON_GRID, capacity_kw=5.0,
                                   latitude=10.0, longitude=76.0, location_name='Kochi')
    return user


class UsersBase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('root', 'root@x.com', 'pw')
        self.client.login(username='root', password='pw')


class UserAccessTests(TestCase):
    def test_anonymous_redirected_and_customer_forbidden(self):
        urls = [reverse('adminpanel:users')]
        customer = make_customer('asha')
        urls += [reverse('adminpanel:user_detail', args=[customer.pk]),
                 reverse('adminpanel:user_delete', args=[customer.pk])]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 302, url)
        self.client.login(username='asha', password='pw')
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.assertEqual(self.client.post(reverse('adminpanel:user_toggle', args=[customer.pk])).status_code, 403)


class UserListTests(UsersBase):
    def setUp(self):
        super().setUp()
        make_customer('asha', 'asha@x.com', 'Asha', 'Nair', system=True)
        make_customer('ravi', 'ravi@y.com', 'Ravi', 'Kumar')
        make_customer('mia', 'mia@x.com', active=False)
        self.url = reverse('adminpanel:users')

    def test_lists_customers_but_not_staff(self):
        resp = self.client.get(self.url)
        for name in ('asha', 'ravi', 'mia'):
            self.assertContains(resp, name)
        self.assertNotContains(resp, 'root@x.com')
        self.assertEqual(resp.context['page'].paginator.count, 3)

    def test_search_by_username_name_and_email(self):
        self.assertEqual(self.client.get(self.url, {'q': 'ravi'}).context['page'].paginator.count, 1)
        self.assertEqual(self.client.get(self.url, {'q': 'Nair'}).context['page'].paginator.count, 1)
        self.assertEqual(self.client.get(self.url, {'q': '@x.com'}).context['page'].paginator.count, 2)

    def test_status_filter(self):
        self.assertEqual(self.client.get(self.url, {'status': 'inactive'}).context['page'].paginator.count, 1)
        self.assertEqual(self.client.get(self.url, {'status': 'active'}).context['page'].paginator.count, 2)

    def test_no_match_message(self):
        self.assertContains(self.client.get(self.url, {'q': 'zzz'}), 'No users match')

    def test_appliance_count_and_system_shown(self):
        asha = User.objects.get(username='asha')
        Appliance.objects.create(user=asha, name='Fridge', category='Cooling', rated_power_w=100, average_usage_hours=10)
        Appliance.objects.create(user=asha, name='Fan', category='Cooling', rated_power_w=50, average_usage_hours=5)
        resp = self.client.get(self.url, {'q': 'asha'})
        self.assertEqual(resp.context['page'][0].appliance_count, 2)
        self.assertContains(resp, 'On-Grid · 5.0 kW')

    def test_paginates_and_keeps_filters(self):
        for i in range(12):
            make_customer(f'bulk{i:02d}', 'b@z.com')
        resp = self.client.get(self.url, {'q': 'bulk'})
        self.assertEqual(len(resp.context['page']), 10)
        self.assertContains(resp, 'q=bulk&page=2')
        self.assertEqual(len(self.client.get(self.url, {'q': 'bulk', 'page': 2}).context['page']), 2)


class UserDetailTests(UsersBase):
    def setUp(self):
        super().setUp()
        self.asha = make_customer('asha', 'asha@x.com', 'Asha', 'Nair', system=True)
        self.url = reverse('adminpanel:user_detail', args=[self.asha.pk])

    def test_shows_account_email_and_system(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, 'asha')
        self.assertContains(resp, 'asha@x.com')
        self.assertContains(resp, 'Kochi')

    def test_page_is_read_only_with_no_edit_form(self):
        resp = self.client.get(self.url)
        self.assertNotContains(resp, 'name="first_name"')
        self.assertNotContains(resp, 'Save changes')

    def test_post_to_detail_is_rejected_and_changes_nothing(self):
        resp = self.client.post(self.url, {'first_name': 'Hacked', 'email': 'evil@x.com'})
        self.assertEqual(resp.status_code, 405)
        self.asha.refresh_from_db()
        self.assertEqual((self.asha.first_name, self.asha.email), ('Asha', 'asha@x.com'))

    def test_staff_accounts_are_not_manageable(self):
        for name in ('adminpanel:user_detail', 'adminpanel:user_delete'):
            self.assertEqual(self.client.get(reverse(name, args=[self.admin.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('adminpanel:user_toggle', args=[self.admin.pk])).status_code, 404)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_unknown_user_is_404(self):
        self.assertEqual(self.client.get(reverse('adminpanel:user_detail', args=[99999])).status_code, 404)


class UserToggleTests(UsersBase):
    def setUp(self):
        super().setUp()
        self.asha = make_customer('asha')
        self.url = reverse('adminpanel:user_toggle', args=[self.asha.pk])

    def test_deactivate_then_reactivate(self):
        self.client.post(self.url)
        self.asha.refresh_from_db()
        self.assertFalse(self.asha.is_active)
        self.client.post(self.url)
        self.asha.refresh_from_db()
        self.assertTrue(self.asha.is_active)

    def test_deactivated_user_cannot_log_in(self):
        self.client.post(self.url)
        other = self.client_class()
        self.assertFalse(other.login(username='asha', password='pw'))

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)


class UserDeleteTests(UsersBase):
    def setUp(self):
        super().setUp()
        self.asha = make_customer('asha', system=True)
        self.ravi = make_customer('ravi', system=True)
        Appliance.objects.create(user=self.asha, name='Fridge', category='Cooling', rated_power_w=100, average_usage_hours=10)
        self.pred = Prediction.objects.create(user=self.asha, prediction_for_date=date.today() + timedelta(days=1),
                                              predicted_generation_kwh=10, capacity_kw_used=5, model_name='RF')
        Prediction.objects.create(user=self.ravi, prediction_for_date=date.today() + timedelta(days=1),
                                  predicted_generation_kwh=9, capacity_kw_used=5, model_name='RF')
        self.url = reverse('adminpanel:user_delete', args=[self.asha.pk])

    def test_confirm_page_lists_what_will_go_and_deletes_nothing(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, '1 appliance')
        self.assertContains(resp, '1 prediction')
        self.assertTrue(User.objects.filter(pk=self.asha.pk).exists())

    def test_post_deletes_user_and_owned_data_only(self):
        resp = self.client.post(self.url, follow=True)
        self.assertRedirects(resp, reverse('adminpanel:users'))
        self.assertContains(resp, 'asha and all their data were deleted')
        self.assertFalse(User.objects.filter(pk=self.asha.pk).exists())
        self.assertFalse(Appliance.objects.filter(name='Fridge').exists())
        self.assertFalse(Prediction.objects.filter(pk=self.pred.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.ravi.pk).exists())
        self.assertEqual(Prediction.objects.filter(user=self.ravi).count(), 1)
        self.assertTrue(SolarSystem.objects.filter(user=self.ravi).exists())