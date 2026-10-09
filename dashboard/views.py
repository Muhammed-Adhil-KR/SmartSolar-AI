import logging

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.shortcuts import render

from forecast.services import (
    WeatherServiceError,
    get_or_fetch_current_weather,
    get_or_fetch_tomorrow_forecast,
)
from solar.decorators import setup_required
from solar.models import Appliance, Battery

logger = logging.getLogger(__name__)


@login_required
@setup_required
def home(request):
    user = request.user
    system = user.solarsystem  # guaranteed by @setup_required

    # --- Weather cards: each is isolated, so one failure never breaks the page ---
    current_weather, current_error = None, None
    try:
        current_weather = get_or_fetch_current_weather(user)
    except WeatherServiceError as exc:
        current_error = str(exc)
    except Exception:
        logger.exception("Unexpected error fetching current weather")
        current_error = "Current weather is temporarily unavailable."

    forecast, forecast_error = None, None
    try:
        forecast = get_or_fetch_tomorrow_forecast(user)
    except WeatherServiceError as exc:
        forecast_error = str(exc)
    except Exception:
        logger.exception("Unexpected error fetching tomorrow's forecast")
        forecast_error = "Tomorrow's forecast is temporarily unavailable."

    # --- System summary (battery/grid shown only if a record exists) ---
    battery = Battery.objects.filter(user=user).first()
    

    # --- Appliance summary ---
    active = Appliance.objects.filter(user=user, is_active=True)
    totals = active.aggregate(total_energy=Sum('daily_energy_kwh'), count=Count('id'))
    appliance_summary = {
        'active_count': totals['count'] or 0,
        'total_energy': round(totals['total_energy'] or 0, 2),
        'shiftable_count': active.filter(is_shiftable=True).count(),
        'inactive_count': Appliance.objects.filter(user=user, is_active=False).count(),
    }

    return render(request, 'dashboard/home.html', {
        'system': system,
        'battery': battery,
        'current_weather': current_weather,
        'current_error': current_error,
        'forecast': forecast,
        'forecast_error': forecast_error,
        'appliance_summary': appliance_summary,
    })