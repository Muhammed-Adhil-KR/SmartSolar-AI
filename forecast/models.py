from django.db import models
from django.contrib.auth.models import User


class WeatherData(models.Model):
    CURRENT = 'CURRENT'
    FORECAST = 'FORECAST'
    WEATHER_TYPE_CHOICES = [
        (CURRENT, 'Current'),
        (FORECAST, 'Forecast'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='weather_records')
    date = models.DateField()
    weather_type = models.CharField(max_length=10, choices=WEATHER_TYPE_CHOICES)

    temperature_c = models.FloatField()
    humidity_percent = models.FloatField(null=True, blank=True)
    wind_speed_mps = models.FloatField(null=True, blank=True)
    rainfall_mm = models.FloatField(default=0)
    solar_irradiance_kwhm2 = models.FloatField(
        null=True, blank=True,
        help_text="Only populated for FORECAST records — this is the ML model's input, not shown for CURRENT."
    )

    # Note: not in the original spec's field list for this table — adding it
    # here for dashboard display only (e.g. "Clear sky", "Light rain"). It is
    # never read by the ML model or the DSS engine, so it doesn't affect
    # anything we've already agreed on; flagging it since it is a schema
    # addition, however small.
    condition = models.CharField(max_length=50, blank=True)

    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'date', 'weather_type')
        ordering = ['-date']

    def __str__(self):
        return f"{self.user.username} - {self.date} - {self.weather_type}"