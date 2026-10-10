"""
Open-Meteo integration. All API communication and unit conversion lives
here, kept out of views per the project's architecture rules. This module
never touches the ML model — that is Phase 9's responsibility.

Design note: rather than mixing Open-Meteo's legacy `current_weather` block
(which uses its own field names like `windspeed`/`weathercode`) with the
`hourly` block's differently-named fields, we request `wind_speed_unit=ms`
so everything — current and hourly — comes back in the same units, and we
only use `current_weather` for temperature/wind/condition, pulling humidity
and rainfall for "now" from the matching hourly timestamp.
"""
import requests
from datetime import date, timedelta
from django.utils import timezone as dj_timezone
import logging
logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# How long a cached CURRENT weather record is considered fresh before we
# bother calling the API again (avoids hitting the API on every page load).
CURRENT_WEATHER_STALE_MINUTES = 30
# Forecasts change slowly, so a longer freshness window is fine.
FORECAST_STALE_MINUTES = 60

WEATHER_CODE_LABELS = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Light freezing rain", 67: "Heavy freezing rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}


class WeatherServiceError(Exception):
    """Raised for any recoverable weather-fetch failure. Views catch this
    and show a friendly message instead of crashing."""
    pass


class WeatherService:
    def __init__(self, latitude, longitude):
        if latitude is None or longitude is None:
            raise WeatherServiceError("Location is not set for this account.")
        self.latitude = latitude
        self.longitude = longitude
        self._raw = None  # cache the raw API response within one instance

    def _fetch_raw(self):
        if self._raw is not None:
            return self._raw

        params = {
                    'latitude': self.latitude,
                    'longitude': self.longitude,
                    'current': 'temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,weather_code',
                    'hourly': 'relative_humidity_2m,precipitation,wind_speed_10m',
                    'daily': 'temperature_2m_mean,precipitation_sum,shortwave_radiation_sum',
                    'wind_speed_unit': 'ms',
                    'timezone': 'auto',
                    'forecast_days': 2,
                }
        try:
            response = requests.get(OPEN_METEO_URL, params=params, timeout=10)
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("Weather request failed: %s", exc)
            raise WeatherServiceError(
                "Could not reach the weather service. Check your internet connection and try again."
            ) from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise WeatherServiceError("Weather service returned an unreadable response.") from exc

        self._raw = data
        return data

    def get_current_weather(self):
        """Returns current conditions for dashboard display."""
        data = self._fetch_raw()
        current = data.get('current')
        if not current:
            raise WeatherServiceError("Weather response is missing current conditions.")

        weather_code = current.get('weather_code')

        return {
        'temperature_c': current.get('temperature_2m'),
        'humidity_percent': current.get('relative_humidity_2m'),
        'wind_speed_mps': current.get('wind_speed_10m'),
        'rainfall_mm': current.get('precipitation', 0),
        'condition': WEATHER_CODE_LABELS.get(weather_code, 'Unknown'),
    }

    def get_tomorrow_forecast(self):
        """
        Returns the ML-ready feature dictionary for tomorrow. Day_of_Year is
        deliberately NOT added here — it's derived from the prediction date
        at inference time in Phase 9, not a property of the weather itself.
        """
        data = self._fetch_raw()
        tomorrow = (date.today() + timedelta(days=1)).isoformat()

        daily = data.get('daily', {})
        daily_times = daily.get('time', [])
        if tomorrow not in daily_times:
            raise WeatherServiceError("Forecast for tomorrow is not available yet.")
        idx = daily_times.index(tomorrow)

        temperature_c = daily.get('temperature_2m_mean', [None])[idx]
        rainfall_mm = daily.get('precipitation_sum', [None])[idx]
        shortwave_mj = daily.get('shortwave_radiation_sum', [None])[idx]

        if temperature_c is None or shortwave_mj is None:
            raise WeatherServiceError("Forecast response is missing required fields.")

        # Required conversion before this reaches the ML model: MJ/m^2 -> kWh/m^2.
        solar_irradiance_kwhm2 = round(shortwave_mj / 3.6, 4)

        # Open-Meteo has no direct "daily mean humidity"/"daily mean wind speed"
        # field, so we derive the true mean from tomorrow's 24 hourly values
        # rather than substituting a different statistic (e.g. daily max).
        hourly = data.get('hourly', {})
        hourly_times = hourly.get('time', [])
        humidity_values, wind_values = [], []
        for i, t in enumerate(hourly_times):
            if t.startswith(tomorrow):
                h_list = hourly.get('relative_humidity_2m', [])
                w_list = hourly.get('wind_speed_10m', [])
                if i < len(h_list) and h_list[i] is not None:
                    humidity_values.append(h_list[i])
                if i < len(w_list) and w_list[i] is not None:
                    wind_values.append(w_list[i])

        if not humidity_values or not wind_values:
            raise WeatherServiceError("Hourly forecast data for tomorrow was not returned.")

        return {
            'date': tomorrow,
            'Temperature_C': round(temperature_c, 2),
            'Humidity_%': round(sum(humidity_values) / len(humidity_values), 2),
            'WindSpeed_mps': round(sum(wind_values) / len(wind_values), 2),
            'Rainfall_mm': round(rainfall_mm, 2) if rainfall_mm is not None else 0,
            'Solar_Irradiance_kWhm2': solar_irradiance_kwhm2,
        }


def get_or_fetch_current_weather(user):
    """
    Returns today's current weather for the user, using a cached WeatherData
    row if fresh enough, otherwise fetching and saving. Raises
    WeatherServiceError if location is missing or the API fails.
    """
    from .models import WeatherData

    system = getattr(user, 'solarsystem', None)
    if not system or not system.has_location:
        raise WeatherServiceError("No location set for this account yet.")

    today = date.today()
    existing = WeatherData.objects.filter(user=user, date=today, weather_type=WeatherData.CURRENT).first()

    if existing:
        age_minutes = (dj_timezone.now() - existing.fetched_at).total_seconds() / 60
        if age_minutes < CURRENT_WEATHER_STALE_MINUTES:
            return {
                'temperature_c': existing.temperature_c,
                'humidity_percent': existing.humidity_percent,
                'wind_speed_mps': existing.wind_speed_mps,
                'rainfall_mm': existing.rainfall_mm,
                'condition': existing.condition,
                'fetched_at': existing.fetched_at,
                'cached': True,
            }

    service = WeatherService(system.latitude, system.longitude)
    weather = service.get_current_weather()

    obj, _ = WeatherData.objects.update_or_create(
        user=user, date=today, weather_type=WeatherData.CURRENT,
        defaults={
            'temperature_c': weather['temperature_c'],
            'humidity_percent': weather['humidity_percent'],
            'wind_speed_mps': weather['wind_speed_mps'],
            'rainfall_mm': weather['rainfall_mm'],
            'condition': weather['condition'],
        }
    )
    weather['fetched_at'] = obj.fetched_at
    weather['cached'] = False
    return weather


def fetch_and_store_tomorrow_forecast(user):
    """
    Fetches tomorrow's forecast, saves it as a FORECAST WeatherData row
    (update_or_create, so re-fetching the same day updates in place rather
    than violating the unique_together constraint), and returns the
    ML-ready feature dictionary.
    """
    from .models import WeatherData

    system = getattr(user, 'solarsystem', None)
    if not system or not system.has_location:
        raise WeatherServiceError("No location set for this account yet.")

    service = WeatherService(system.latitude, system.longitude)
    forecast = service.get_tomorrow_forecast()

    WeatherData.objects.update_or_create(
        user=user, date=forecast['date'], weather_type=WeatherData.FORECAST,
        defaults={
            'temperature_c': forecast['Temperature_C'],
            'humidity_percent': forecast['Humidity_%'],
            'wind_speed_mps': forecast['WindSpeed_mps'],
            'rainfall_mm': forecast['Rainfall_mm'],
            'solar_irradiance_kwhm2': forecast['Solar_Irradiance_kWhm2'],
        }
    )
    return forecast

def get_or_fetch_tomorrow_forecast(user):
    """
    Returns tomorrow's FORECAST WeatherData row for the dashboard, reusing the
    stored row if it is fresh and fetching/updating it otherwise. Returns the
    model instance (not the ML dictionary) because templates can't read keys
    like 'Humidity_%'. The ML-ready dictionary from
    fetch_and_store_tomorrow_forecast() is still what Phase 9 will use.
    """
    from .models import WeatherData

    tomorrow = date.today() + timedelta(days=1)
    existing = WeatherData.objects.filter(
        user=user, date=tomorrow, weather_type=WeatherData.FORECAST
    ).first()

    if existing and existing.solar_irradiance_kwhm2 is not None:
        age_minutes = (dj_timezone.now() - existing.fetched_at).total_seconds() / 60
        if age_minutes < FORECAST_STALE_MINUTES:
            return existing

    fetch_and_store_tomorrow_forecast(user)
    return WeatherData.objects.get(user=user, date=tomorrow, weather_type=WeatherData.FORECAST)