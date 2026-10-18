from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from forecast.services import WeatherServiceError
from solar.models import GridConfiguration, SolarSystem


def make_user(name='sunny'):
    user = User.objects.create_user(name, password='pw12345!x')
    SolarSystem.objects.create(user=user, system_type=SolarSystem.ON_GRID, capacity_kw=3.0,
                               latitude=10.0, longitude=76.0, location_name='Kochi')
    GridConfiguration.objects.create(user=user, import_tariff_per_kwh=7.0)   # completes setup
    return user


def weather(condition='Clear sky', rain=0.0):
    """What get_or_fetch_current_weather() returns: a plain dict."""
    return {'temperature_c': 31.2, 'humidity_percent': 62, 'wind_speed_mps': 3.4,
            'rainfall_mm': rain, 'condition': condition,
            'fetched_at': timezone.now(), 'cached': False}


# The tomorrow forecast is not what these tests are about, so it is switched off for all of them.
@patch('dashboard.views.get_or_fetch_tomorrow_forecast', side_effect=WeatherServiceError('forecast down'))
class DashboardWeatherCardTests(TestCase):
    def setUp(self):
        make_user()
        self.client.login(username='sunny', password='pw12345!x')
        self.url = reverse('dashboard:home')

    def test_shows_conditions_and_the_sunshine_outlook(self, _f):
        with patch('dashboard.views.get_or_fetch_current_weather', return_value=weather('Clear sky')):
            resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '31.2°C')
        self.assertContains(resp, 'Clear sky')
        self.assertContains(resp, 'Sunshine outlook right now')
        self.assertContains(resp, 'Excellent')

    def test_rain_gives_a_poor_outlook(self, _f):
        with patch('dashboard.views.get_or_fetch_current_weather', return_value=weather('Slight rain', rain=2.0)):
            resp = self.client.get(self.url)
        self.assertContains(resp, 'Poor')

    def test_unknown_condition_hides_the_outlook_but_still_renders(self, _f):
        with patch('dashboard.views.get_or_fetch_current_weather', return_value=weather('Dust whirls')):
            resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Dust whirls')
        self.assertNotContains(resp, 'Sunshine outlook right now')

    def test_current_weather_failure_shows_the_message_not_a_crash(self, _f):
        with patch('dashboard.views.get_or_fetch_current_weather', side_effect=WeatherServiceError('API down')):
            resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'API down')
        self.assertNotContains(resp, 'Sunshine outlook right now')

    def test_unexpected_weather_error_is_friendly(self, _f):
        with patch('dashboard.views.get_or_fetch_current_weather', side_effect=RuntimeError('oops')):
            with self.assertLogs('dashboard.views', level='ERROR'):
                resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'temporarily unavailable')
        self.assertNotContains(resp, 'oops')

    def test_forecast_failure_does_not_hide_the_current_weather(self, _f):
        with patch('dashboard.views.get_or_fetch_current_weather', return_value=weather('Overcast')):
            resp = self.client.get(self.url)
        self.assertContains(resp, 'Overcast')
        self.assertContains(resp, 'forecast down')