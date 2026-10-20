from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from forecast.models import Prediction


def make_prediction(user, days_ahead=1, kwh=10.0):
    return Prediction.objects.create(
        user=user, prediction_for_date=date.today() + timedelta(days=days_ahead),
        predicted_generation_kwh=kwh, capacity_kw_used=5, model_name='RF')


class PredictionsBase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('root', 'root@x.com', 'pw')
        self.client.login(username='root', password='pw')
        self.url = reverse('adminpanel:predictions')


class PredictionAccessTests(TestCase):
    def test_anonymous_and_customer_are_blocked(self):
        owner = User.objects.create_user('asha', password='pw')
        item = make_prediction(owner)
        urls = [reverse('adminpanel:predictions'), reverse('adminpanel:prediction_delete', args=[item.pk])]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 302, url)
        self.client.login(username='asha', password='pw')
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.assertEqual(self.client.post(urls[1]).status_code, 403)
        self.assertTrue(Prediction.objects.filter(pk=item.pk).exists())


class PredictionListTests(PredictionsBase):
    def setUp(self):
        super().setUp()
        self.asha = User.objects.create_user('asha', password='pw')
        self.ravi = User.objects.create_user('ravi', password='pw')
        make_prediction(self.asha, 1, 11.5)
        make_prediction(self.asha, -5, 9.5)
        make_prediction(self.ravi, 1, 14.5)

    def test_lists_customers_but_not_staff(self):
        make_prediction(self.admin, 1, 77.7)
        resp = self.client.get(self.url)
        self.assertEqual(resp.context['page'].paginator.count, 3)
        self.assertNotContains(resp, '77.7')

    def test_newest_date_first(self):
        dates = [p.prediction_for_date for p in self.client.get(self.url).context['page']]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_search_by_owner(self):
        self.assertEqual(self.client.get(self.url, {'q': 'ravi'}).context['page'].paginator.count, 1)

    def test_date_range_filters(self):
        today = date.today()
        get = lambda **kw: self.client.get(self.url, kw).context['page'].paginator.count
        self.assertEqual(get(date_from=today.isoformat()), 2)
        self.assertEqual(get(date_to=today.isoformat()), 1)
        self.assertEqual(get(date_from=(today - timedelta(days=10)).isoformat(),
                             date_to=(today - timedelta(days=1)).isoformat()), 1)

    def test_invalid_date_is_ignored_not_a_crash(self):
        resp = self.client.get(self.url, {'date_from': 'not-a-date'})
        self.assertEqual(resp.status_code, 200)

    def test_owner_filter_and_banner(self):
        resp = self.client.get(self.url, {'user': self.asha.pk})
        self.assertEqual(resp.context['page'].paginator.count, 2)
        self.assertContains(resp, 'Showing predictions of')

    def test_no_match_message(self):
        self.assertContains(self.client.get(self.url, {'q': 'zzz'}), 'No predictions match')

    def test_paginates_and_keeps_filters(self):
        for i in range(12):
            make_prediction(self.ravi, i + 5, 10 + i)
        resp = self.client.get(self.url, {'q': 'ravi'})
        self.assertEqual(len(resp.context['page']), 10)
        self.assertContains(resp, 'q=ravi&page=2')

    def test_user_detail_links_to_filtered_list(self):
        resp = self.client.get(reverse('adminpanel:user_detail', args=[self.asha.pk]))
        self.assertContains(resp, f'{self.url}?user={self.asha.pk}')


class PredictionDeleteTests(PredictionsBase):
    def setUp(self):
        super().setUp()
        self.asha = User.objects.create_user('asha', password='pw')
        self.ravi = User.objects.create_user('ravi', password='pw')
        self.item = make_prediction(self.asha, 1, 12.5)
        self.other = make_prediction(self.ravi, 1, 9.5)
        self.delete = reverse('adminpanel:prediction_delete', args=[self.item.pk])

    def test_confirm_page_deletes_nothing(self):
        resp = self.client.get(self.delete)
        self.assertContains(resp, 'asha')
        self.assertContains(resp, '12.5 kWh')
        self.assertTrue(Prediction.objects.filter(pk=self.item.pk).exists())

    def test_post_deletes_only_that_prediction(self):
        resp = self.client.post(self.delete, follow=True)
        self.assertRedirects(resp, self.url)
        self.assertContains(resp, 'was deleted')
        self.assertFalse(Prediction.objects.filter(pk=self.item.pk).exists())
        self.assertTrue(Prediction.objects.filter(pk=self.other.pk).exists())

    def test_post_returns_to_next_page(self):
        back = self.url + '?q=asha'
        resp = self.client.post(self.delete, {'next': back})
        self.assertRedirects(resp, back, fetch_redirect_response=False)

    def test_off_site_next_is_ignored(self):
        resp = self.client.post(self.delete, {'next': 'https://evil.example/x'})
        self.assertRedirects(resp, self.url, fetch_redirect_response=False)

    def test_staff_owned_prediction_is_404(self):
        mine = make_prediction(self.admin, 3, 5.0)
        self.assertEqual(self.client.get(reverse('adminpanel:prediction_delete', args=[mine.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('adminpanel:prediction_delete', args=[mine.pk])).status_code, 404)
        self.assertTrue(Prediction.objects.filter(pk=mine.pk).exists())