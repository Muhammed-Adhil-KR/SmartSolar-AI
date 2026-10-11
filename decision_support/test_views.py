from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from decision_support.forms import RecommendationFilterForm
from decision_support.models import Recommendation as Rec
from decision_support.services import generate_recommendations
from decision_support.tests import WINDOW, add_appliance, make_prediction, make_user
from solar.models import SolarSystem

TOMORROW = date.today() + timedelta(days=1)


def add_rec(user, prediction, rtype=Rec.GENERAL, priority=Rec.LOW, title='Tip', message='Msg', **kw):
    return Rec.objects.create(user=user, prediction=prediction, recommendation_type=rtype,
                              priority=priority, title=title, message=message, **kw)


def day_prediction(user, days_ago):
    return make_prediction(user, 9.0, on=date.today() - timedelta(days=days_ago))


class AccessTests(TestCase):
    def test_anonymous_users_are_sent_to_login(self):
        for name in ('current', 'history'):
            resp = self.client.get(reverse(f'decision_support:{name}'))
            self.assertEqual(resp.status_code, 302)
            self.assertIn('login', resp.url)

    def test_incomplete_setup_is_sent_to_setup(self):
        User.objects.create_user('new', password='pw')
        self.client.login(username='new', password='pw')
        resp = self.client.get(reverse('decision_support:current'))
        self.assertRedirects(resp, reverse('solar:setup_system'), fetch_redirect_response=False)


class TomorrowPageTests(TestCase):
    def setUp(self):
        self.user = make_user('HYBRID')
        add_appliance(self.user, 'Fan', 1000, 20)
        self.client.login(username='asha', password='pw')
        self.url = reverse('decision_support:current')

    def test_no_prediction_empty_state_links_to_dashboard(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, 'No prediction for tomorrow yet')
        self.assertNotContains(resp, 'Refresh recommendations')

    def test_prediction_without_recommendations_explains_and_offers_refresh(self):
        make_prediction(self.user, 9.0)
        resp = self.client.get(self.url)
        self.assertContains(resp, 'No recommendations yet')
        self.assertContains(resp, 'Refresh recommendations')

    def test_cards_are_ordered_by_priority(self):
        pred = make_prediction(self.user, 9.0)
        add_rec(self.user, pred, priority=Rec.LOW, title='low-one')
        add_rec(self.user, pred, priority=Rec.CRITICAL, title='critical-one')
        add_rec(self.user, pred, priority=Rec.MEDIUM, title='medium-one')
        add_rec(self.user, pred, priority=Rec.HIGH, title='high-one')
        html = self.client.get(self.url).content.decode()
        positions = [html.index(t) for t in ('critical-one', 'high-one', 'medium-one', 'low-one')]
        self.assertEqual(positions, sorted(positions))

    def test_card_shows_priority_label_chips_and_currency(self):
        pred = make_prediction(self.user, 9.0)
        fan = self.user.appliances.first()
        add_rec(self.user, pred, Rec.APPLIANCE_SCHEDULE, Rec.MEDIUM, 'Run Fan', 'Run it at noon',
                appliance=fan, estimated_energy_kwh=3.0, estimated_savings=21.0)
        resp = self.client.get(self.url)
        self.assertContains(resp, 'Medium')
        self.assertContains(resp, 'Appliance scheduling')
        self.assertContains(resp, 'Fan')
        self.assertContains(resp, '3.0 kWh')
        self.assertContains(resp, '₹21')

    def test_hybrid_shows_grid_and_battery_tiles(self):
        pred = make_prediction(self.user, 9.0)
        generate_recommendations(self.user, pred, window=WINDOW)
        resp = self.client.get(self.url)
        self.assertContains(resp, 'Expected grid import')
        self.assertContains(resp, 'Battery supply')
        self.assertContains(resp, 'Usage covered by solar')

    def test_off_grid_has_no_grid_tile(self):
        user = make_user('OFF_GRID', name='off')
        add_appliance(user, 'Fan', 1000, 20)
        generate_recommendations(user, make_prediction(user, 9.0), window=WINDOW)
        self.client.login(username='off', password='pw')
        resp = self.client.get(self.url)
        self.assertContains(resp, 'Battery supply')
        self.assertNotContains(resp, 'Expected grid import')

    def test_on_grid_has_no_battery_tile(self):
        user = make_user('ON_GRID', name='on')
        add_appliance(user, 'Fan', 1000, 20)
        generate_recommendations(user, make_prediction(user, 9.0), window=WINDOW)
        self.client.login(username='on', password='pw')
        resp = self.client.get(self.url)
        self.assertContains(resp, 'Expected grid import')
        self.assertNotContains(resp, 'Battery supply')

    def test_only_own_recommendations_are_shown(self):
        other = make_user('ON_GRID', name='other')
        add_rec(other, make_prediction(other, 9.0), title='SECRET-OTHER')
        add_rec(self.user, make_prediction(self.user, 9.0), title='MINE')
        resp = self.client.get(self.url)
        self.assertContains(resp, 'MINE')
        self.assertNotContains(resp, 'SECRET-OTHER')


class RefreshTests(TestCase):
    def setUp(self):
        self.user = make_user('ON_GRID')
        add_appliance(self.user, 'Fan', 1000, 12)
        self.client.login(username='asha', password='pw')
        self.url = reverse('decision_support:refresh')

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    @patch('decision_support.services.get_solar_window', return_value=WINDOW)
    def test_refresh_rebuilds_recommendations(self, _w):
        make_prediction(self.user, 9.0)
        resp = self.client.post(self.url, follow=True)
        self.assertRedirects(resp, reverse('decision_support:current'))
        self.assertGreater(Rec.objects.filter(user=self.user).count(), 0)
        self.assertContains(resp, 'refreshed')

    def test_refresh_without_prediction_warns_and_creates_nothing(self):
        resp = self.client.post(self.url, follow=True)
        self.assertContains(resp, 'prediction first')
        self.assertEqual(Rec.objects.count(), 0)

    def test_unexpected_error_is_friendly(self):
        make_prediction(self.user, 9.0)
        with patch('decision_support.views.generate_recommendations', side_effect=RuntimeError('boom')):
            with self.assertLogs('decision_support.views', level='ERROR'):
                resp = self.client.post(self.url, follow=True)
        self.assertContains(resp, 'Something went wrong')
        self.assertNotContains(resp, 'boom')

    @patch('decision_support.services.get_solar_window', return_value=WINDOW)
    def test_next_dashboard_returns_to_dashboard(self, _w):
        make_prediction(self.user, 9.0)
        resp = self.client.post(self.url, {'next': 'dashboard'})
        self.assertRedirects(resp, reverse('dashboard:home'), fetch_redirect_response=False)

    def test_anonymous_cannot_refresh(self):
        self.client.logout()
        self.assertEqual(self.client.post(self.url).status_code, 302)


class HistoryPageTests(TestCase):
    def setUp(self):
        self.user = make_user('HYBRID')
        self.client.login(username='asha', password='pw')
        self.url = reverse('decision_support:history')
        self.d1, self.d2, self.d3 = (day_prediction(self.user, n) for n in (1, 2, 3))
        add_rec(self.user, self.d1, Rec.GRID_IMPORT, Rec.HIGH, 'import-d1')
        add_rec(self.user, self.d1, Rec.GENERAL, Rec.LOW, 'summary-d1')
        add_rec(self.user, self.d2, Rec.BATTERY_RESERVE, Rec.HIGH, 'reserve-d2')
        add_rec(self.user, self.d3, Rec.GRID_IMPORT, Rec.MEDIUM, 'import-d3')

    def test_groups_by_day_newest_first(self):
        resp = self.client.get(self.url)
        days = resp.context['days']
        self.assertEqual([d['date'] for d in days], [self.d1.prediction_for_date,
                                                      self.d2.prediction_for_date,
                                                      self.d3.prediction_for_date])
        self.assertEqual([r.title for r in days[0]['recs']], ['import-d1', 'summary-d1'])   # priority order
        self.assertEqual(days[0]['top'].title, 'import-d1')

    def test_filter_by_type(self):
        resp = self.client.get(self.url, {'recommendation_type': Rec.GRID_IMPORT})
        titles = [r.title for d in resp.context['days'] for r in d['recs']]
        self.assertEqual(sorted(titles), ['import-d1', 'import-d3'])

    def test_filter_by_priority(self):
        resp = self.client.get(self.url, {'priority': Rec.HIGH})
        titles = [r.title for d in resp.context['days'] for r in d['recs']]
        self.assertEqual(sorted(titles), ['import-d1', 'reserve-d2'])

    def test_filter_by_date_range(self):
        d = self.d2.prediction_for_date.isoformat()
        resp = self.client.get(self.url, {'date_from': d, 'date_to': d})
        self.assertEqual([x['date'] for x in resp.context['days']], [self.d2.prediction_for_date])

    def test_filters_combine(self):
        resp = self.client.get(self.url, {'recommendation_type': Rec.GRID_IMPORT, 'priority': Rec.MEDIUM})
        titles = [r.title for d in resp.context['days'] for r in d['recs']]
        self.assertEqual(titles, ['import-d3'])

    def test_no_match_shows_filtered_empty_state(self):
        resp = self.client.get(self.url, {'recommendation_type': Rec.GRID_EXPORT})
        self.assertContains(resp, 'No recommendations match these filters')

    def test_from_after_to_shows_error_and_does_not_filter(self):
        resp = self.client.get(self.url, {'date_from': '2026-12-31', 'date_to': '2026-01-01'})
        self.assertContains(resp, 'must be on or before')
        self.assertEqual(len(resp.context['days']), 3)

    def test_garbage_date_is_a_form_error_not_a_crash(self):
        resp = self.client.get(self.url, {'date_from': 'not-a-date'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Enter a valid date')

    def test_empty_history_state(self):
        Rec.objects.all().delete()
        self.assertContains(self.client.get(self.url), 'appear here after you generate a prediction')

    def test_only_own_history(self):
        other = make_user('ON_GRID', name='other')
        add_rec(other, day_prediction(other, 1), title='SECRET-OTHER')
        self.assertNotContains(self.client.get(self.url), 'SECRET-OTHER')

    def test_paginates_by_day_and_keeps_filters_in_links(self):
        for n in range(4, 12):                                   # 8 more days -> 11 days total
            add_rec(self.user, day_prediction(self.user, n), Rec.GRID_IMPORT, Rec.MEDIUM, f'extra-{n}')
        resp = self.client.get(self.url, {'recommendation_type': Rec.GRID_IMPORT})
        self.assertEqual(len(resp.context['days']), 7)
        self.assertContains(resp, 'recommendation_type=GRID_IMPORT&amp;page=2')
        page2 = self.client.get(self.url, {'recommendation_type': Rec.GRID_IMPORT, 'page': 2})
        self.assertEqual(len(page2.context['days']), 3)          # 10 matching days: d1, d3, 8 extras -> 7 + 3

    def test_filter_choices_follow_system_type(self):
        hybrid = [v for v, _ in RecommendationFilterForm(system=self.user.solarsystem).fields['recommendation_type'].choices]
        self.assertIn(Rec.BATTERY_CHARGE, hybrid)
        self.assertIn(Rec.GRID_EXPORT, hybrid)
        on = make_user('ON_GRID', name='on')
        on_choices = [v for v, _ in RecommendationFilterForm(system=on.solarsystem).fields['recommendation_type'].choices]
        self.assertNotIn(Rec.BATTERY_CHARGE, on_choices)
        self.assertIn(Rec.GRID_EXPORT, on_choices)
        off = make_user('OFF_GRID', name='off')
        off_choices = [v for v, _ in RecommendationFilterForm(system=off.solarsystem).fields['recommendation_type'].choices]
        self.assertNotIn(Rec.GRID_IMPORT, off_choices)
        self.assertIn(Rec.BATTERY_DISCHARGE, off_choices)


class DashboardAdviceCardTests(TestCase):
    def setUp(self):
        self.user = make_user('HYBRID')
        add_appliance(self.user, 'Fan', 1000, 20)
        self.client.login(username='asha', password='pw')
        self.url = reverse('dashboard:home')
        self.weather = patch('dashboard.views.get_or_fetch_current_weather', return_value={'temperature_c': 30})
        self.weather.start()
        self.addCleanup(self.weather.stop)

    def test_no_prediction_no_card(self):
        self.assertNotContains(self.client.get(self.url), 'Advice for tomorrow')

    def test_prediction_without_recs_offers_refresh(self):
        make_prediction(self.user, 9.0)
        resp = self.client.get(self.url)
        self.assertContains(resp, 'Advice for tomorrow')
        self.assertContains(resp, 'name="next" value="dashboard"')

    def test_shows_three_most_important_and_view_all_link(self):
        pred = make_prediction(self.user, 9.0)
        add_rec(self.user, pred, priority=Rec.LOW, title='low-one')
        add_rec(self.user, pred, priority=Rec.MEDIUM, title='medium-one')
        add_rec(self.user, pred, priority=Rec.CRITICAL, title='critical-one')
        add_rec(self.user, pred, priority=Rec.HIGH, title='high-one')
        resp = self.client.get(self.url)
        self.assertContains(resp, 'critical-one')
        self.assertContains(resp, 'high-one')
        self.assertContains(resp, 'medium-one')
        self.assertNotContains(resp, 'low-one')
        self.assertContains(resp, 'View all 4')