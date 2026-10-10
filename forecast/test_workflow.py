from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from solar.models import GridConfiguration, SolarSystem
from forecast.models import Prediction, WeatherData
from forecast.prediction_service import PredictionError
from forecast.services import WeatherServiceError
from forecast.workflow import generate_tomorrow_prediction

TOMORROW = date.today() + timedelta(days=1)


def fake_fetch(user):
    """Stands in for the real weather service: stores a FORECAST row, returns the dict."""
    WeatherData.objects.update_or_create(
        user=user, date=TOMORROW, weather_type=WeatherData.FORECAST,
        defaults={'temperature_c': 30.0, 'humidity_percent': 70, 'wind_speed_mps': 2.0,
                  'rainfall_mm': 1.0, 'solar_irradiance_kwhm2': 5.5})
    return {'date': TOMORROW.isoformat(), 'Temperature_C': 30.0, 'Humidity_%': 70,
            'WindSpeed_mps': 2.0, 'Rainfall_mm': 1.0, 'Solar_Irradiance_kWhm2': 5.5}


def make_user(name='asha', capacity=5.0, lat=10.0, lon=76.0):
    user = User.objects.create_user(name, password='pw')
    SolarSystem.objects.create(user=user, system_type=SolarSystem.ON_GRID, capacity_kw=capacity,
                               latitude=lat, longitude=lon, location_name='Test')
    GridConfiguration.objects.create(user=user, import_tariff_per_kwh=7.0)  # completes setup
    return user


@patch('forecast.workflow.fetch_and_store_tomorrow_forecast', side_effect=fake_fetch)
class WorkflowTests(TestCase):
    def setUp(self):
        self.user = make_user()

    @patch('forecast.workflow.predict_generation', return_value=21.5)
    def test_creates_prediction_with_capacity_and_weather(self, mock_predict, _f):
        prediction, created = generate_tomorrow_prediction(self.user)
        self.assertTrue(created)
        self.assertEqual(prediction.predicted_generation_kwh, 21.5)
        self.assertEqual(prediction.capacity_kw_used, 5.0)
        self.assertEqual(prediction.prediction_for_date, TOMORROW)
        self.assertIsNotNone(prediction.weather_data)
        self.assertEqual(mock_predict.call_args.args[2], 5.0)   # capacity passed through

    @patch('forecast.workflow.predict_generation', return_value=10.0)
    def test_recalculation_updates_the_same_row(self, _p, _f):
        first, _ = generate_tomorrow_prediction(self.user)
        old_time = first.created_at
        with patch('forecast.workflow.predict_generation', return_value=12.0):
            second, created = generate_tomorrow_prediction(self.user)
        self.assertFalse(created)
        self.assertEqual(Prediction.objects.filter(user=self.user).count(), 1)
        self.assertEqual(second.predicted_generation_kwh, 12.0)
        self.assertGreater(second.created_at, old_time)

    def test_requires_a_solar_system(self, _f):
        bare = User.objects.create_user('bare', password='pw')
        with self.assertRaises(PredictionError):
            generate_tomorrow_prediction(bare)

    def test_model_failure_saves_nothing(self, _f):
        with patch('forecast.workflow.predict_generation', side_effect=PredictionError('boom')):
            with self.assertRaises(PredictionError):
                generate_tomorrow_prediction(self.user)
        self.assertEqual(Prediction.objects.count(), 0)

    @patch('forecast.workflow.predict_generation', return_value=10.0)
    def test_prediction_survives_weather_row_deletion(self, _p, _f):
        prediction, _ = generate_tomorrow_prediction(self.user)
        WeatherData.objects.all().delete()
        prediction.refresh_from_db()
        self.assertIsNone(prediction.weather_data)


class ViewTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.login(username='asha', password='pw')
        self.url = reverse('forecast:generate_prediction')
        # The DSS has its own tests; here we only test the prediction view.
        patcher = patch('forecast.views.generate_recommendations', return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)

    @patch('forecast.workflow.predict_generation', return_value=18.25)
    @patch('forecast.workflow.fetch_and_store_tomorrow_forecast', side_effect=fake_fetch)
    def test_post_generates_and_redirects_with_message(self, _f, _p):
        resp = self.client.post(self.url, follow=True)
        self.assertRedirects(resp, reverse('dashboard:home'))
        self.assertContains(resp, '18.25 kWh')
        self.assertTrue(Prediction.objects.filter(user=self.user).exists())

    @patch('forecast.workflow.predict_generation', return_value=18.25)
    @patch('forecast.workflow.fetch_and_store_tomorrow_forecast', side_effect=fake_fetch)
    def test_success_message_reports_recommendation_count(self, _f, _p):
        with patch('forecast.views.generate_recommendations', return_value=[1, 2, 3]):
            resp = self.client.post(self.url, follow=True)
        self.assertContains(resp, '3 recommendations ready')

    @patch('forecast.workflow.predict_generation', return_value=18.25)
    @patch('forecast.workflow.fetch_and_store_tomorrow_forecast', side_effect=fake_fetch)
    def test_dss_failure_does_not_hide_or_undo_the_prediction(self, _f, _p):
        with patch('forecast.views.generate_recommendations', side_effect=RuntimeError('dss broke')):
            with self.assertLogs('forecast.views', level='ERROR'):
                resp = self.client.post(self.url, follow=True)
        self.assertContains(resp, '18.25 kWh')
        self.assertContains(resp, 'recommendations could not be generated')
        self.assertTrue(Prediction.objects.filter(user=self.user).exists())

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()
        resp = self.client.post(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp.url)

    @patch('forecast.workflow.fetch_and_store_tomorrow_forecast', side_effect=WeatherServiceError('API down'))
    def test_weather_failure_shows_message_and_saves_nothing(self, _f):
        resp = self.client.post(self.url, follow=True)
        self.assertContains(resp, 'API down')
        self.assertEqual(Prediction.objects.count(), 0)

    @patch('forecast.workflow.predict_generation', side_effect=PredictionError('model missing'))
    @patch('forecast.workflow.fetch_and_store_tomorrow_forecast', side_effect=fake_fetch)
    def test_model_failure_shows_message(self, _f, _p):
        resp = self.client.post(self.url, follow=True)
        self.assertContains(resp, 'model missing')
        self.assertEqual(Prediction.objects.count(), 0)

    @patch('forecast.workflow.fetch_and_store_tomorrow_forecast', side_effect=RuntimeError('oops'))
    def test_unexpected_error_is_friendly(self, _f):
        with self.assertLogs('forecast.views', level='ERROR'):
            resp = self.client.post(self.url, follow=True)
        self.assertContains(resp, 'Something went wrong')
        self.assertNotContains(resp, 'oops')


class HistoryAndDashboardTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.other = make_user('ravi', capacity=2.0)
        self.client.login(username='asha', password='pw')

    def _make(self, user, days_ahead, kwh):
        return Prediction.objects.create(
            user=user, prediction_for_date=date.today() + timedelta(days=days_ahead),
            predicted_generation_kwh=kwh, capacity_kw_used=user.solarsystem.capacity_kw,
            model_name='RF')

    def test_history_empty_state(self):
        resp = self.client.get(reverse('forecast:prediction_history'))
        self.assertContains(resp, 'No predictions yet')

    def test_history_shows_only_own_predictions(self):
        self._make(self.user, 1, 11.11)
        self._make(self.other, 1, 99.99)
        resp = self.client.get(reverse('forecast:prediction_history'))
        self.assertContains(resp, '11.11')
        self.assertNotContains(resp, '99.99')

    def test_history_paginates(self):
        for i in range(12):
            self._make(self.user, i - 11, 10 + i)
        resp = self.client.get(reverse('forecast:prediction_history'))
        self.assertEqual(len(resp.context['page']), 10)
        self.assertEqual(len(resp.context['chart']['values']), 12)
        resp2 = self.client.get(reverse('forecast:prediction_history') + '?page=2')
        self.assertEqual(len(resp2.context['page']), 2)

    @patch('dashboard.views.get_or_fetch_current_weather', return_value={'temperature_c': 30})
    def test_dashboard_empty_then_filled(self, _w):
        resp = self.client.get(reverse('dashboard:home'))
        self.assertContains(resp, 'No prediction for tomorrow yet')
        self.assertContains(resp, 'Generate Prediction')
        self._make(self.user, 1, 17.5)
        resp = self.client.get(reverse('dashboard:home'))
        self.assertContains(resp, '17.5')
        self.assertContains(resp, 'Recalculate')

    @patch('dashboard.views.get_or_fetch_current_weather', return_value={'temperature_c': 30})
    def test_dashboard_load_does_not_generate(self, _w):
        self.client.get(reverse('dashboard:home'))
        self.assertEqual(Prediction.objects.count(), 0)


class StalePredictionSignalTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.system = self.user.solarsystem
        self.today = Prediction.objects.create(
            user=self.user, prediction_for_date=date.today(), predicted_generation_kwh=10,
            capacity_kw_used=5, model_name='RF')
        self.future = Prediction.objects.create(
            user=self.user, prediction_for_date=date.today() + timedelta(days=1),
            predicted_generation_kwh=11, capacity_kw_used=5, model_name='RF')
        self.past = Prediction.objects.create(
            user=self.user, prediction_for_date=date.today() - timedelta(days=3),
            predicted_generation_kwh=9, capacity_kw_used=5, model_name='RF')
        self.weather = WeatherData.objects.create(
            user=self.user, date=date.today() + timedelta(days=1),
            weather_type=WeatherData.FORECAST, temperature_c=30)

    def test_capacity_change_deletes_today_and_future_predictions_only(self):
        self.system.capacity_kw = 8.0
        self.system.save()
        remaining = list(Prediction.objects.values_list('pk', flat=True))
        self.assertEqual(remaining, [self.past.pk])
        self.assertTrue(WeatherData.objects.filter(pk=self.weather.pk).exists())  # weather still valid

    def test_location_change_deletes_weather_and_predictions(self):
        self.system.latitude = 12.5
        self.system.save()
        self.assertEqual(list(Prediction.objects.values_list('pk', flat=True)), [self.past.pk])
        self.assertFalse(WeatherData.objects.filter(pk=self.weather.pk).exists())

    def test_unrelated_edit_keeps_everything(self):
        self.system.panel_count = 12
        self.system.save()
        self.assertEqual(Prediction.objects.count(), 3)
        self.assertEqual(WeatherData.objects.count(), 1)

    def test_other_users_data_untouched(self):
        other = make_user('ravi')
        Prediction.objects.create(user=other, prediction_for_date=date.today() + timedelta(days=1),
                                  predicted_generation_kwh=5, capacity_kw_used=5, model_name='RF')
        self.system.capacity_kw = 9.0
        self.system.save()
        self.assertEqual(Prediction.objects.filter(user=other).count(), 1)
