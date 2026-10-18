from types import SimpleNamespace

from django.test import SimpleTestCase

from dashboard.weather_view import describe_weather


def wx(condition, rain=0.0):
    return SimpleNamespace(condition=condition, rainfall_mm=rain)


class DescribeWeatherTests(SimpleTestCase):
    def test_none_when_no_record(self):
        self.assertIsNone(describe_weather(None))

    def test_clear_sky_is_excellent(self):
        info = describe_weather(wx('Clear sky'))
        self.assertEqual(info['label'], 'Excellent')
        self.assertEqual(info['icon'], 'bi-sun-fill')
        self.assertEqual(info['tone'], 'excellent')

    def test_partly_cloudy_is_good_not_just_cloudy(self):
        self.assertEqual(describe_weather(wx('Partly cloudy'))['label'], 'Good')

    def test_mainly_clear_is_good(self):
        self.assertEqual(describe_weather(wx('Mainly clear'))['label'], 'Good')

    def test_overcast_and_cloudy_are_fair(self):
        self.assertEqual(describe_weather(wx('Overcast'))['label'], 'Fair')
        self.assertEqual(describe_weather(wx('Cloudy'))['label'], 'Fair')

    def test_rain_and_thunder_are_poor(self):
        self.assertEqual(describe_weather(wx('Light rain'))['label'], 'Poor')
        self.assertEqual(describe_weather(wx('Thunderstorm'))['label'], 'Poor')

    def test_measured_rain_downgrades_a_clear_label(self):
        info = describe_weather(wx('Partly cloudy', rain=1.2))
        self.assertEqual(info['label'], 'Poor')
        self.assertLessEqual(info['level'], 25)

    def test_unknown_condition_has_no_label(self):
        info = describe_weather(wx('Dust whirls'))
        self.assertEqual(info['label'], '')
        self.assertEqual(info['tone'], 'unknown')
        self.assertEqual(info['level'], 0)
        
    def test_accepts_a_plain_dict(self):
        info = describe_weather({'condition': 'Clear sky', 'rainfall_mm': 0.0})
        self.assertEqual(info['label'], 'Excellent')

    def test_empty_dict_counts_as_no_weather(self):
        self.assertIsNone(describe_weather({}))