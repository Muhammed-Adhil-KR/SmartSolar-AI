"""
Prediction workflow: weather -> ML model -> stored Prediction.

This is the only place that connects the weather service to the ML service.
It makes no decisions about what to do with the number (that is the DSS's job).
"""
from datetime import date

from django.conf import settings
from django.utils import timezone

from .models import Prediction, WeatherData
from .prediction_service import PredictionError, predict_generation
from .services import fetch_and_store_tomorrow_forecast


def generate_tomorrow_prediction(user):
    """
    Fetch tomorrow's forecast, run the model, and save the result.
    Returns (prediction, created). Re-running for the same day updates the
    existing row, so there is only ever one prediction per user per date.
    Raises WeatherServiceError / PredictionError on failure (nothing is saved).
    """
    system = getattr(user, 'solarsystem', None)
    if system is None:
        raise PredictionError("Set up your solar system before generating a prediction.")

    forecast = fetch_and_store_tomorrow_forecast(user)      # dict, also saved as WeatherData
    target_date = date.fromisoformat(forecast['date'])
    weather_row = WeatherData.objects.filter(
        user=user, date=target_date, weather_type=WeatherData.FORECAST).first()

    kwh = predict_generation(forecast, target_date, system.capacity_kw)

    return Prediction.objects.update_or_create(
        user=user,
        prediction_for_date=target_date,
        defaults={
            'weather_data': weather_row,
            'predicted_generation_kwh': kwh,
            'capacity_kw_used': system.capacity_kw,
            'model_name': settings.ML_MODEL_NAME,
            'created_at': timezone.now(),
        },
    )