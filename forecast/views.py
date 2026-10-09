import json
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from solar.decorators import setup_required
from .services import get_or_fetch_current_weather, fetch_and_store_tomorrow_forecast, WeatherServiceError


@login_required
@setup_required
def weather_test(request):
    """
    Temporary Phase 7 verification page — lets us inspect the exact
    dictionaries WeatherService produces before Phase 8 (dashboard) and
    Phase 9 (ML inference) are built on top of them. Will be replaced by
    the real dashboard integration later.
    """
    current_weather = None
    forecast = None
    forecast_json = None
    error = None

    try:
        current_weather = get_or_fetch_current_weather(request.user)
    except WeatherServiceError as e:
        error = str(e)

    if not error:
        try:
            forecast = fetch_and_store_tomorrow_forecast(request.user)
            forecast_json = json.dumps(forecast, indent=4)
        except WeatherServiceError as e:
            error = str(e)

    return render(request, 'forecast/weather_test.html', {
        'current_weather': current_weather,
        'forecast_json': forecast_json,
        'error': error,
    })