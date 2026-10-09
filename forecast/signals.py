from datetime import date

from django.db.models.signals import pre_save
from django.dispatch import receiver

from solar.models import SolarSystem
from .models import WeatherData


@receiver(pre_save, sender=SolarSystem)
def clear_weather_on_location_change(sender, instance, **kwargs):
    """
    If a solar system's coordinates change, today's/future cached weather
    belongs to the OLD place, so delete it. The next dashboard visit
    refetches for the new location. Past rows are kept for traceability.
    """
    if not instance.pk:
        return
    old = SolarSystem.objects.filter(pk=instance.pk).first()
    if old is None:
        return
    if (old.latitude, old.longitude) != (instance.latitude, instance.longitude):
        WeatherData.objects.filter(user=instance.user, date__gte=date.today()).delete()