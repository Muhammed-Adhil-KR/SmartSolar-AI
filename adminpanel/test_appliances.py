from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from solar.models import Appliance


def make_customer(name):
    return User.objects.create_user(name, password='pw')


def make_appliance(user, name='Fridge', category='Cooling', priority=Appliance.MEDIUM,
                   active=True, watts=100, hours=10):
    return Appliance.objects.create(user=user, name=name, category=category, priority=priority,
                                    is_active=active, rated_power_w=watts, average_usage_hours=hours)


class AppliancesBase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('root', 'root@x.com', 'pw')
        self.client.login(username='root', password='pw')
        # The DSS has its own tests; here we only check that the owner's advice refresh is requested.
        patcher = patch('adminpanel.views.refresh_open_recommendations', return_value=False)
        self.refresh = patcher.start()
        self.addCleanup(patcher.stop)
        self.url = reverse('adminpanel:appliances')


class AccessTests(TestCase):
    def test_anonymous_and_customer_are_blocked(self):
        owner = make_customer('asha')
        item = make_appliance(owner)
        urls = [reverse('adminpanel:appliances'),
                reverse('adminpanel:appliance_delete', args=[item.pk])]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 302, url)
        toggle = reverse('adminpanel:appliance_toggle', args=[item.pk])
        self.assertEqual(self.client.post(toggle).status_code, 302)
        self.client.login(username='asha', password='pw')
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.assertEqual(self.client.post(toggle).status_code, 403)
        item.refresh_from_db()
        self.assertTrue(item.is_active)


class ApplianceListTests(AppliancesBase):
    def setUp(self):
        super().setUp()
        self.asha = make_customer('asha')
        self.ravi = make_customer('ravi')
        make_appliance(self.asha, 'Fridge', 'Cooling', Appliance.CRITICAL)
        make_appliance(self.asha, 'Washer', 'Laundry', Appliance.LOW, active=False)
        make_appliance(self.ravi, 'Heater', 'Heating', Appliance.HIGH)

    def test_lists_customer_appliances_but_not_staff(self):
        make_appliance(self.admin, 'AdminKettle')
        resp = self.client.get(self.url)
        self.assertEqual(resp.context['page'].paginator.count, 3)
        self.assertNotContains(resp, 'AdminKettle')

    def test_search_by_name_category_and_owner(self):
        count = lambda q: self.client.get(self.url, {'q': q}).context['page'].paginator.count
        self.assertEqual(count('fridge'), 1)
        self.assertEqual(count('Laundry'), 1)
        self.assertEqual(count('asha'), 2)

    def test_priority_and_status_filters(self):
        get = lambda **kw: self.client.get(self.url, kw).context['page'].paginator.count
        self.assertEqual(get(priority='CRITICAL'), 1)
        self.assertEqual(get(status='inactive'), 1)
        self.assertEqual(get(status='active'), 2)
        self.assertEqual(get(priority='LOW', status='active'), 0)

    def test_owner_filter_and_banner(self):
        resp = self.client.get(self.url, {'user': self.ravi.pk})
        self.assertEqual(resp.context['page'].paginator.count, 1)
        self.assertContains(resp, 'Showing appliances of')
        self.assertEqual(resp.context['owner'], self.ravi)

    def test_unknown_owner_filter_is_ignored(self):
        resp = self.client.get(self.url, {'user': 99999})
        self.assertEqual(resp.context['page'].paginator.count, 3)

    def test_no_match_message(self):
        self.assertContains(self.client.get(self.url, {'q': 'zzz'}), 'No appliances match')

    def test_paginates_and_keeps_filters(self):
        for i in range(12):
            make_appliance(self.ravi, f'Gadget{i:02d}')
        resp = self.client.get(self.url, {'q': 'Gadget'})
        self.assertEqual(len(resp.context['page']), 10)
        self.assertContains(resp, 'q=Gadget&page=2')

    def test_user_detail_links_to_filtered_list(self):
        resp = self.client.get(reverse('adminpanel:user_detail', args=[self.asha.pk]))
        self.assertContains(resp, f'{self.url}?user={self.asha.pk}')


class ApplianceToggleTests(AppliancesBase):
    def setUp(self):
        super().setUp()
        self.asha = make_customer('asha')
        self.item = make_appliance(self.asha)
        self.toggle = reverse('adminpanel:appliance_toggle', args=[self.item.pk])

    def test_toggle_flips_and_returns_to_next(self):
        back = self.url + '?q=fri&status=active'
        resp = self.client.post(self.toggle, {'next': back})
        self.assertRedirects(resp, back, fetch_redirect_response=False)
        self.item.refresh_from_db()
        self.assertFalse(self.item.is_active)
        self.client.post(self.toggle)
        self.item.refresh_from_db()
        self.assertTrue(self.item.is_active)

    def test_toggle_keeps_the_energy_figure(self):
        self.client.post(self.toggle)
        self.item.refresh_from_db()
        self.assertEqual(self.item.daily_energy_kwh, 1.0)

    def test_off_site_next_is_ignored(self):
        resp = self.client.post(self.toggle, {'next': 'https://evil.example/steal'})
        self.assertRedirects(resp, self.url, fetch_redirect_response=False)

    def test_refreshes_owners_advice_and_tells_admin(self):
        self.refresh.return_value = True
        resp = self.client.post(self.toggle, follow=True)
        self.refresh.assert_called_once_with(self.asha)
        self.assertContains(resp, 'recommendations were updated to match this change')

    def test_no_update_message_when_nothing_changed(self):
        resp = self.client.post(self.toggle, follow=True)
        self.assertNotContains(resp, 'recommendations were updated')

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(self.toggle).status_code, 405)

    def test_staff_owned_appliance_is_not_manageable(self):
        mine = make_appliance(self.admin, 'AdminKettle')
        self.assertEqual(self.client.post(reverse('adminpanel:appliance_toggle', args=[mine.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('adminpanel:appliance_delete', args=[mine.pk])).status_code, 404)


class ApplianceDeleteTests(AppliancesBase):
    def setUp(self):
        super().setUp()
        self.asha = make_customer('asha')
        self.ravi = make_customer('ravi')
        self.item = make_appliance(self.asha, 'Fridge')
        self.other = make_appliance(self.ravi, 'Heater')
        self.delete = reverse('adminpanel:appliance_delete', args=[self.item.pk])

    def test_confirm_page_deletes_nothing(self):
        resp = self.client.get(self.delete)
        self.assertContains(resp, 'Fridge')
        self.assertContains(resp, 'asha')
        self.assertTrue(Appliance.objects.filter(pk=self.item.pk).exists())

    def test_post_deletes_only_that_appliance_and_refreshes_owner(self):
        resp = self.client.post(self.delete, follow=True)
        self.assertRedirects(resp, self.url)
        self.assertContains(resp, 'Fridge (asha) was deleted')
        self.assertFalse(Appliance.objects.filter(pk=self.item.pk).exists())
        self.assertTrue(Appliance.objects.filter(pk=self.other.pk).exists())
        self.refresh.assert_called_once_with(self.asha)

    def test_post_returns_to_next_page(self):
        back = self.url + '?user=' + str(self.asha.pk)
        resp = self.client.post(self.delete, {'next': back})
        self.assertRedirects(resp, back, fetch_redirect_response=False)

    def test_confirm_page_keeps_next_for_cancel(self):
        back = self.url + '?q=fri'
        resp = self.client.get(self.delete, {'next': back})
        self.assertContains(resp, f'href="{back}"')