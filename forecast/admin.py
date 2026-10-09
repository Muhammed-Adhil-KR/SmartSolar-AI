from django.contrib import admin
from .models import WeatherData


@admin.register(WeatherData)
class WeatherDataAdmin(admin.ModelAdmin):
    list_display = ('user', 'date', 'weather_type', 'temperature_c', 'humidity_percent',
                     'wind_speed_mps', 'rainfall_mm', 'solar_irradiance_kwhm2', 'fetched_at')
    list_filter = ('weather_type',)
    search_fields = ('user__username',)