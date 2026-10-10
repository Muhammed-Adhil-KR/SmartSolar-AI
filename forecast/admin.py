from django.contrib import admin
from .models import Prediction, WeatherData


@admin.register(WeatherData)
class WeatherDataAdmin(admin.ModelAdmin):
    list_display = ('user', 'date', 'weather_type', 'temperature_c', 'humidity_percent',
                     'wind_speed_mps', 'rainfall_mm', 'solar_irradiance_kwhm2', 'fetched_at')
    list_filter = ('weather_type',)
    search_fields = ('user__username',)
    
@admin.register(Prediction)
class PredictionAdmin(admin.ModelAdmin):
    list_display = ('user', 'prediction_for_date', 'predicted_generation_kwh',
                    'capacity_kw_used', 'model_name', 'created_at')
    list_filter = ('model_name',)
    search_fields = ('user__username',)
    date_hierarchy = 'prediction_for_date'