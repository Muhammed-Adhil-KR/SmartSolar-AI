from django.db import models
from django.contrib.auth.models import User


class Profile(models.Model):
    """
    Extends Django's built-in User with the extra fields our project needs.
    One-to-one so every user has exactly one profile.
    Location fields here represent the household's location, used later by
    the forecast app to fetch weather for the correct place (Phase 7+).
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')

    phone = models.CharField(max_length=15, blank=True)

    location_name = models.CharField(
        max_length=255, blank=True,
        help_text="e.g. 'Thiruvananthapuram, Kerala' — for display purposes only."
    )
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Profile of {self.user.username}"

    @property
    def has_location(self):
        """Used by later phases to check if setup is complete."""
        return self.latitude is not None and self.longitude is not None

from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    """
    Ensures a Profile always exists for every User, without the
    registration view needing to create it explicitly.
    """
    if created:
        Profile.objects.create(user=instance)
    else:
        # Profile might not exist yet for users created before this signal
        # existed (e.g. via createsuperuser before this code was added).
        Profile.objects.get_or_create(user=instance)