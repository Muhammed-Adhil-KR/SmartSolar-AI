"""
Recommended solar-availability window for one day.

This is a SEPARATE signal from the daily ML prediction: it uses Open-Meteo's
hourly shortwave radiation (W/m2) to find when the sun is strongest, so the
DSS can suggest running flexible appliances then. It is never presented as an
hourly ML forecast.

Never raises: if the hourly data can't be fetched or parsed, the configured
default window (settings.DSS_DEFAULT_SOLAR_WINDOW) is returned instead.
"""
import logging
from dataclasses import dataclass
from typing import Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


@dataclass(frozen=True)
class SolarWindow:
    start_hour: int                 # inclusive, 24h clock
    end_hour: int                   # exclusive
    source: str                     # 'hourly' (from tomorrow's data) or 'default'
    peak_wm2: Optional[float] = None
    weak: bool = False              # True when sunlight is too weak to be worth shifting loads for

    @property
    def label(self):
        return f"{self.start_hour:02d}:00–{self.end_hour:02d}:00"

    @property
    def source_note(self):
        return ("based on tomorrow's hourly sunlight" if self.source == 'hourly'
                else "typical sunny hours; hourly sunlight data was unavailable")


def default_window(weak=False, peak=None):
    start, end = settings.DSS_DEFAULT_SOLAR_WINDOW
    return SolarWindow(start, end, 'default', peak, weak)


def compute_window(hourly_wm2):
    """
    hourly_wm2: 24 irradiance values (index = hour of day).
    Returns the SolarWindow for the longest run of hours at or above
    DSS_WINDOW_PEAK_FRACTION of the day's peak, or None if the data is unusable.
    """
    if not hourly_wm2 or len(hourly_wm2) != 24:
        return None
    values = [float(v) if v is not None else 0.0 for v in hourly_wm2]
    peak = max(values)
    if peak < settings.DSS_MIN_PEAK_IRRADIANCE_WM2:
        return default_window(weak=True, peak=round(peak, 0))

    threshold = peak * settings.DSS_WINDOW_PEAK_FRACTION
    best = (0, 0)                      # (start, length)
    start = None
    for hour, value in enumerate(values + [0.0]):    # sentinel closes a run that ends at midnight
        if value >= threshold and start is None:
            start = hour
        elif value < threshold and start is not None:
            if hour - start > best[1]:
                best = (start, hour - start)
            start = None
    return SolarWindow(best[0], best[0] + best[1], 'hourly', round(peak, 0), False)


def get_solar_window(solar_system, target_date):
    """Fetch tomorrow's hourly sunlight for the system's location and compute the window."""
    if solar_system is None or not solar_system.has_location:
        return default_window()
    try:
        response = requests.get(OPEN_METEO_URL, params={
            'latitude': solar_system.latitude,
            'longitude': solar_system.longitude,
            'hourly': 'shortwave_radiation',
            'timezone': 'auto',
            'start_date': target_date.isoformat(),
            'end_date': target_date.isoformat(),
        }, timeout=8)
        response.raise_for_status()
        window = compute_window(response.json()['hourly']['shortwave_radiation'])
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        logger.warning("Hourly sunlight request failed, using default window: %s", exc)
        return default_window()
    return window or default_window()
