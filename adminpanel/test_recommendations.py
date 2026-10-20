from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from decision_support.models import Recommendation
from forecast.models import Prediction


def make_prediction(user, days_ahead):
    return Prediction.objects.create(
        user=user, prediction_for_date=date.today() + timedelta(days=days_ahead),
        predicted_generation_kwh=10, capacity_kw_used=5, model_name='RF')


def make_rec(user, days_ahead=-3, title='Run the washer at noon', rtype=Recommendation.APPLIANCE_SCHEDULE,
             priority=Recommendation.MEDIUM, prediction=None, kwh=None):
    prediction = prediction or make_prediction(user, days_ahead)
    return Recommendation.objects.create(
        user=user, prediction=prediction, recommendation_type=rtype, title=title,
        message=f'{title}: details', priority=priority, estimated_energy_kwh=kwh)


class RecsBase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('root', 'root@x.com', 'pw')
        self.client.login(username='root', password='pw')
        self.url = reverse('adminpanel:recommendations')


class RecommendationAccessTests(TestCase):
    def test_anonymous_and_customer_are_blocked(self):
        owner = User.objects.create_user('asha', password='pw')
        rec = make_rec(owner)
        urls = [reverse('adminpanel:recommendations'), reverse('adminpanel:recommendation_delete', args=[rec.pk])]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 302, url)
        self.client.login(username='asha', password='pw')
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.assertEqual(self.client.post(urls[1]).status_code, 403)
        self.assertTrue(Recommendation.objects.filter(pk=rec.pk).exists())


class RecommendationListTests(RecsBase):
    def setUp(self):
        super().setUp()
        self.asha = User.objects.create_user('asha', password='pw')
        self.ravi = User.objects.create_user('ravi', password='pw')
        make_rec(self.asha, -3, 'Run the washer at noon', Recommendation.APPLIANCE_SCHEDULE, Recommendation.LOW, kwh=1.5)
        make_rec(self.asha, -2, 'Charge the battery early', Recommendation.BATTERY_CHARGE, Recommendation.HIGH)
        make_rec(self.ravi, 1, 'Export surplus power', Recommendation.GRID_EXPORT, Recommendation.CRITICAL)

    def test_lists_customers_but_not_staff(self):
        make_rec(self.admin, -1, 'Admin only tip')
        resp = self.client.get(self.url)
        self.assertEqual(resp.context['page'].paginator.count, 3)
        self.assertNotContains(resp, 'Admin only tip')

    def test_newest_day_first(self):
        days = [r.prediction.prediction_for_date for r in self.client.get(self.url).context['page']]
        self.assertEqual(days, sorted(days, reverse=True))

    def test_priority_order_within_one_day(self):
        pred = make_prediction(self.ravi, -10)
        make_rec(self.ravi, title='Low tip', priority=Recommendation.LOW, prediction=pred)
        make_rec(self.ravi, title='Critical tip', priority=Recommendation.CRITICAL, prediction=pred)
        resp = self.client.get(self.url, {'q': 'ravi', 'date_to': (date.today() - timedelta(days=5)).isoformat()})
        self.assertEqual([r.title for r in resp.context['page']], ['Critical tip', 'Low tip'])

    def test_search_by_owner_and_title(self):
        count = lambda q: self.client.get(self.url, {'q': q}).context['page'].paginator.count
        self.assertEqual(count('ravi'), 1)
        self.assertEqual(count('washer'), 1)
        self.assertEqual(count('zzz'), 0)

    def test_type_and_priority_filters(self):
        get = lambda **kw: self.client.get(self.url, kw).context['page'].paginator.count
        self.assertEqual(get(recommendation_type=Recommendation.BATTERY_CHARGE), 1)
        self.assertEqual(get(priority=Recommendation.CRITICAL), 1)
        self.assertEqual(get(recommendation_type=Recommendation.GRID_EXPORT, priority=Recommendation.LOW), 0)

    def test_date_range_filters_on_the_day_advice_is_for(self):
        today = date.today()
        get = lambda **kw: self.client.get(self.url, kw).context['page'].paginator.count
        self.assertEqual(get(date_from=today.isoformat()), 1)
        self.assertEqual(get(date_to=(today - timedelta(days=3)).isoformat()), 1)

    def test_invalid_date_is_ignored_not_a_crash(self):
        self.assertEqual(self.client.get(self.url, {'date_from': 'nope'}).status_code, 200)

    def test_owner_filter_and_banner(self):
        resp = self.client.get(self.url, {'user': self.asha.pk})
        self.assertEqual(resp.context['page'].paginator.count, 2)
        self.assertContains(resp, 'Showing recommendations of')

    def test_impact_is_shown(self):
        self.assertContains(self.client.get(self.url, {'q': 'washer'}), '1.50 kWh')

    def test_no_match_message(self):
        self.assertContains(self.client.get(self.url, {'q': 'zzz'}), 'No recommendations match')

    def test_paginates_and_keeps_filters(self):
        pred = make_prediction(self.ravi, -20)
        for i in range(12):
            make_rec(self.ravi, title=f'Tip {i:02d}', prediction=pred)
        resp = self.client.get(self.url, {'q': 'ravi'})
        self.assertEqual(len(resp.context['page']), 10)
        self.assertContains(resp, 'q=ravi&page=2')

    def test_delete_button_only_on_past_rows(self):
        past = Recommendation.objects.get(title='Run the washer at noon')
        future = Recommendation.objects.get(title='Export surplus power')
        resp = self.client.get(self.url)
        self.assertContains(resp, reverse('adminpanel:recommendation_delete', args=[past.pk]))
        self.assertNotContains(resp, reverse('adminpanel:recommendation_delete', args=[future.pk]))

    def test_user_detail_links_to_filtered_list(self):
        resp = self.client.get(reverse('adminpanel:user_detail', args=[self.asha.pk]))
        self.assertContains(resp, f'{self.url}?user={self.asha.pk}')


class RecommendationDeleteTests(RecsBase):
    def setUp(self):
        super().setUp()
        self.asha = User.objects.create_user('asha', password='pw')
        pred = make_prediction(self.asha, -4)
        self.rec = make_rec(self.asha, title='Old tip', prediction=pred)
        self.sibling = make_rec(self.asha, title='Sibling tip', prediction=pred)
        self.delete = reverse('adminpanel:recommendation_delete', args=[self.rec.pk])

    def test_confirm_page_deletes_nothing(self):
        resp = self.client.get(self.delete)
        self.assertContains(resp, 'Old tip')
        self.assertContains(resp, 'asha')
        self.assertTrue(Recommendation.objects.filter(pk=self.rec.pk).exists())

    def test_post_deletes_only_that_recommendation(self):
        resp = self.client.post(self.delete, follow=True)
        self.assertRedirects(resp, self.url)
        self.assertContains(resp, 'was deleted')
        self.assertFalse(Recommendation.objects.filter(pk=self.rec.pk).exists())
        self.assertTrue(Recommendation.objects.filter(pk=self.sibling.pk).exists())
        self.assertTrue(Prediction.objects.filter(pk=self.rec.prediction_id).exists())

    def test_post_returns_to_next_page_and_ignores_off_site_next(self):
        back = self.url + '?user=' + str(self.asha.pk)
        self.assertRedirects(self.client.post(self.delete, {'next': back}), back, fetch_redirect_response=False)

    def test_off_site_next_is_ignored(self):
        resp = self.client.post(self.delete, {'next': 'https://evil.example/x'})
        self.assertRedirects(resp, self.url, fetch_redirect_response=False)

    def test_upcoming_recommendation_cannot_be_deleted(self):
        upcoming = make_rec(self.asha, 1, 'Tomorrow tip')
        url = reverse('adminpanel:recommendation_delete', args=[upcoming.pk])
        for resp in (self.client.get(url, follow=True), self.client.post(url, follow=True)):
            self.assertContains(resp, 'Only past recommendations can be deleted')
        self.assertTrue(Recommendation.objects.filter(pk=upcoming.pk).exists())

    def test_staff_owned_recommendation_is_404(self):
        mine = make_rec(self.admin, -2, 'Admin tip')
        url = reverse('adminpanel:recommendation_delete', args=[mine.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url).status_code, 404)
        self.assertTrue(Recommendation.objects.filter(pk=mine.pk).exists())