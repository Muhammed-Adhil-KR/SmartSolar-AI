from datetime import date

from django.db.models.signals import pre_save
from django.dispatch import receiver

from solar.models import SolarSystem
from .models import Prediction, WeatherData


@receiver(pre_save, sender=SolarSystem)
def clear_stale_data_on_system_change(sender, instance, **kwargs):
    """
    Today's/future cached data was computed for the OLD setup, so remove it.
      - location changed  -> weather AND predictions are stale
      - capacity changed  -> predictions are stale (weather is still valid)
    Past rows are kept as history.
    """
    if not instance.pk:
        return
    old = SolarSystem.objects.filter(pk=instance.pk).first()
    if old is None:
        return

    today = date.today()
    if (old.latitude, old.longitude) != (instance.latitude, instance.longitude):
        WeatherData.objects.filter(user=instance.user, date__gte=today).delete()
        Prediction.objects.filter(user=instance.user, prediction_for_date__gte=today).delete()
    elif old.capacity_kw != instance.capacity_kw:
        Prediction.objects.filter(user=instance.user, prediction_for_date__gte=today).delete()