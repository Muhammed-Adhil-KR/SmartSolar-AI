from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from forecast.models import Prediction
from solar.models import Appliance, Battery, GridConfiguration, SolarSystem


def make_system(name, system_type=SolarSystem.ON_GRID, capacity=5.0, location='Kochi', with_location=True):
    user = User.objects.create_user(name, password='pw')
    system = SolarSystem.objects.create(
        user=user, system_type=system_type, capacity_kw=capacity, location_name=location,
        latitude=10.0 if with_location else None, longitude=76.0 if with_location else None)
    return user, system


class SystemsBase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('root', 'root@x.com', 'pw')
        self.client.login(username='root', password='pw')
        self.url = reverse('adminpanel:systems')


class SystemAccessTests(TestCase):
    def test_anonymous_and_customer_are_blocked(self):
        _, system = make_system('asha')
        urls = [reverse('adminpanel:systems'), reverse('adminpanel:system_detail', args=[system.pk])]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 302, url)
        self.client.login(username='asha', password='pw')
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 403, url)


class SystemListTests(SystemsBase):
    def setUp(self):
        super().setUp()
        self.asha, _ = make_system('asha', SolarSystem.ON_GRID, location='Kochi')
        GridConfiguration.objects.create(user=self.asha, import_tariff_per_kwh=7)
        self.ravi, _ = make_system('ravi', SolarSystem.HYBRID, location='Pune')
        self.mia, _ = make_system('mia', SolarSystem.OFF_GRID, location='', with_location=False)

    def test_lists_customer_systems_but_not_staff(self):
        SolarSystem.objects.create(user=self.admin, system_type=SolarSystem.ON_GRID, capacity_kw=3,
                                   latitude=1.0, longitude=1.0, location_name='AdminHQ')
        resp = self.client.get(self.url)
        self.assertEqual(resp.context['page'].paginator.count, 3)
        self.assertNotContains(resp, 'AdminHQ')

    def test_search_by_owner_and_location(self):
        count = lambda q: self.client.get(self.url, {'q': q}).context['page'].paginator.count
        self.assertEqual(count('ravi'), 1)
        self.assertEqual(count('Kochi'), 1)
        self.assertEqual(count('zzz'), 0)

    def test_type_filter(self):
        resp = self.client.get(self.url, {'system_type': SolarSystem.HYBRID})
        self.assertEqual(resp.context['page'].paginator.count, 1)

    def test_setup_status_labels(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, 'Complete')           # asha: on-grid with grid config
        self.assertContains(resp, 'Battery missing')    # ravi: hybrid, no battery
        self.assertContains(resp, 'Location missing')   # mia: no coordinates

    def test_complete_after_battery_and_grid_added(self):
        Battery.objects.create(user=self.ravi, capacity_kwh=5)
        GridConfiguration.objects.create(user=self.ravi, import_tariff_per_kwh=7)
        resp = self.client.get(self.url, {'q': 'ravi'})
        self.assertContains(resp, 'Complete')
        self.assertNotContains(resp, 'Battery missing')

    def test_no_match_message(self):
        self.assertContains(self.client.get(self.url, {'q': 'zzz'}), 'No systems match')


class SystemDetailTests(SystemsBase):
    def test_shows_system_battery_grid_and_activity(self):
        user, system = make_system('ravi', SolarSystem.HYBRID, capacity=7.5, location='Pune')
        Battery.objects.create(user=user, capacity_kwh=5, current_soc_percent=60, minimum_soc_percent=20)
        GridConfiguration.objects.create(user=user, import_tariff_per_kwh=7.5, export_enabled=True)
        Appliance.objects.create(user=user, name='Fridge', category='Cooling', rated_power_w=100, average_usage_hours=10)
        Prediction.objects.create(user=user, prediction_for_date=date.today() + timedelta(days=1),
                                  predicted_generation_kwh=21.5, capacity_kw_used=7.5, model_name='RF')
        resp = self.client.get(reverse('adminpanel:system_detail', args=[system.pk]))
        self.assertContains(resp, 'Hybrid')
        self.assertContains(resp, '7.5 kW')
        self.assertContains(resp, 'Pune')
        self.assertContains(resp, '5.0 kWh')            # battery capacity
        self.assertContains(resp, '7.5 per kWh')        # import tariff
        self.assertContains(resp, '21.5 kWh')           # latest prediction

    def test_missing_battery_is_flagged_when_required(self):
        _, system = make_system('ravi', SolarSystem.HYBRID)
        resp = self.client.get(reverse('adminpanel:system_detail', args=[system.pk]))
        self.assertContains(resp, 'Required for this system type but not configured yet')

    def test_not_needed_message_for_on_grid_battery(self):
        _, system = make_system('asha', SolarSystem.ON_GRID)
        resp = self.client.get(reverse('adminpanel:system_detail', args=[system.pk]))
        self.assertContains(resp, 'Not needed for this system type')

    def test_page_is_read_only(self):
        user, system = make_system('asha')
        url = reverse('adminpanel:system_detail', args=[system.pk])
        self.assertEqual(self.client.post(url, {'capacity_kw': 99}).status_code, 405)
        system.refresh_from_db()
        self.assertEqual(system.capacity_kw, 5.0)

    def test_staff_system_is_404(self):
        mine = SolarSystem.objects.create(user=self.admin, system_type=SolarSystem.ON_GRID, capacity_kw=3,
                                          latitude=1.0, longitude=1.0)
        self.assertEqual(self.client.get(reverse('adminpanel:system_detail', args=[mine.pk])).status_code, 404)

    def test_user_detail_links_to_system(self):
        user, system = make_system('asha')
        resp = self.client.get(reverse('adminpanel:user_detail', args=[user.pk]))
        self.assertContains(resp, reverse('adminpanel:system_detail', args=[system.pk]))