"""
Recommendations depend on the user's appliances, battery, grid settings and
system type. When any of those change, today's/future recommendations are stale,
so they are deleted (past ones stay as history). The user regenerates them
from the Recommendations page or by generating a new prediction.

Location and capacity changes already delete the Prediction, and the
Recommendation -> Prediction CASCADE removes the advice with it.
"""
from datetime import date

from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from solar.models import Appliance, Battery, GridConfiguration, SolarSystem
from .models import Recommendation


def clear_stale_recommendations(user_id):
    Recommendation.objects.filter(
        user_id=user_id, prediction__prediction_for_date__gte=date.today()).delete()


@receiver([post_save, post_delete], sender=Appliance)
@receiver([post_save, post_delete], sender=Battery)
@receiver([post_save, post_delete], sender=GridConfiguration)
def clear_on_inputs_changed(sender, instance, **kwargs):
    clear_stale_recommendations(instance.user_id)


@receiver(pre_save, sender=SolarSystem)
def clear_on_system_type_change(sender, instance, **kwargs):
    if not instance.pk:
        return
    old = SolarSystem.objects.filter(pk=instance.pk).first()
    if old is not None and old.system_type != instance.system_type:
        clear_stale_recommendations(instance.user_id)
