from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from adminpanel.services import overview_stats
from forecast.models import Prediction
from solar.models import SolarSystem


def make_user(name, staff=False, active=True, system_type=None, capacity=5.0):
    user = User.objects.create_user(name, password='pw', is_staff=staff, is_active=active)
    if system_type:
        SolarSystem.objects.create(user=user, system_type=system_type, capacity_kw=capacity,
                                   latitude=10.0, longitude=76.0, location_name='Test')
    return user


def make_prediction(user, days_ahead=0, kwh=10):
    return Prediction.objects.create(
        user=user, prediction_for_date=date.today() + timedelta(days=days_ahead),
        predicted_generation_kwh=kwh, capacity_kw_used=5, model_name='RF')


class AccessTests(TestCase):
    def setUp(self):
        self.url = reverse('adminpanel:overview')

    def test_url_is_under_manage(self):
        self.assertEqual(self.url, '/manage/')

    def test_anonymous_is_sent_to_login(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp.url)

    def test_regular_user_gets_403(self):
        make_user('asha')
        self.client.login(username='asha', password='pw')
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_staff_user_sees_overview(self):
        make_user('boss', staff=True)
        self.client.login(username='boss', password='pw')
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Admin panel')

    def test_403_page_is_friendly(self):
        make_user('asha')
        self.client.login(username='asha', password='pw')
        resp = self.client.get(self.url)
        self.assertContains(resp, "don't have access", status_code=403)


class NavbarTests(TestCase):
    def test_staff_sees_admin_link(self):
        make_user('boss', staff=True)
        self.client.login(username='boss', password='pw')
        resp = self.client.get(reverse('adminpanel:overview'))
        self.assertContains(resp, 'href="/manage/"')

    def test_staff_nav_has_no_customer_features(self):
        make_user('boss', staff=True)
        self.client.login(username='boss', password='pw')
        resp = self.client.get(reverse('adminpanel:overview'))
        for name in ('dashboard:home', 'solar:appliance_list', 'forecast:prediction_history',
                     'decision_support:current', 'accounts:profile', 'solar:edit_system'):
            self.assertNotContains(resp, f'href="{reverse(name)}"')

    def test_regular_user_does_not_see_admin_link(self):
        make_user('asha')
        self.client.login(username='asha', password='pw')
        resp = self.client.get(reverse('accounts:profile'))
        self.assertNotContains(resp, 'href="/manage/"')
        self.assertContains(resp, f'href="{reverse("solar:appliance_list")}"')

    def test_django_admin_link_only_for_superuser(self):
        User.objects.create_user('staffer', password='pw', is_staff=True)
        self.client.login(username='staffer', password='pw')
        self.assertNotContains(self.client.get(reverse('adminpanel:overview')), 'Django admin')
        self.client.logout()
        User.objects.create_superuser('root', 'r@x.com', 'pw')
        self.client.login(username='root', password='pw')
        self.assertContains(self.client.get(reverse('adminpanel:overview')), 'Django admin')


class OverviewStatsTests(TestCase):
    def setUp(self):
        self.boss = make_user('boss', staff=True)
        self.asha = make_user('asha', system_type=SolarSystem.ON_GRID)
        make_user('ravi', system_type=SolarSystem.ON_GRID)
        make_user('mia', active=False)

    def test_user_counts_exclude_staff(self):
        stats = overview_stats()
        self.assertEqual(stats['users_total'], 3)
        self.assertEqual(stats['users_active'], 2)
        self.assertEqual(stats['staff_total'], 1)
        self.assertEqual(stats['users_new_week'], 3)

    def test_old_accounts_are_not_new(self):
        User.objects.filter(username='mia').update(date_joined=timezone.now() - timedelta(days=30))
        self.assertEqual(overview_stats()['users_new_week'], 2)

    def test_systems_grouped_by_type(self):
        stats = overview_stats()
        self.assertEqual(stats['systems_total'], 2)
        self.assertEqual(sum(row['count'] for row in stats['systems_by_type']), 2)
        self.assertEqual(len(stats['systems_by_type']), 1)

    def test_staff_data_is_not_counted(self):
        SolarSystem.objects.create(user=self.boss, system_type=SolarSystem.HYBRID, capacity_kw=3,
                                   latitude=10.0, longitude=76.0, location_name='Admin home')
        make_prediction(self.boss)
        make_prediction(self.asha)
        stats = overview_stats()
        self.assertEqual(stats['systems_total'], 2)
        self.assertEqual(stats['predictions_total'], 1)
        self.assertEqual(sum(stats['predictions_chart']['values']), 1)
        self.assertEqual([p.user.username for p in stats['recent_predictions']], ['asha'])
        self.assertEqual([row['label'] for row in stats['systems_by_type']], ['On-Grid'])

    def test_predictions_chart_covers_14_days_and_counts(self):
        make_prediction(self.asha, 0)
        make_prediction(self.asha, -30, 9)
        chart = overview_stats()['predictions_chart']
        self.assertEqual(len(chart['labels']), 14)
        self.assertEqual(chart['values'][-1], 1)
        self.assertEqual(sum(chart['values']), 1)          # the 30-day-old one is outside the window

    def test_overview_page_renders_with_data(self):
        make_prediction(self.asha, 0, 12.5)
        self.client.login(username='boss', password='pw')
        resp = self.client.get(reverse('adminpanel:overview'))
        self.assertContains(resp, 'asha')
        self.assertContains(resp, '12.5 kWh')

    def test_overview_page_renders_when_empty(self):
        User.objects.exclude(username='boss').delete()
        self.client.login(username='boss', password='pw')
        resp = self.client.get(reverse('adminpanel:overview'))
        self.assertContains(resp, 'No users yet')
        self.assertContains(resp, 'No systems set up yet')