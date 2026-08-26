"""
Central place that defines what "setup complete" means for a user,
so this logic is never duplicated across views.
"""
from functools import wraps
from django.shortcuts import redirect
from .models import SolarSystem, Battery, GridConfiguration


def setup_status(user):
    solar_system = SolarSystem.objects.filter(user=user).first()
    return {
        'has_location': hasattr(user, 'profile') and user.profile.has_location,
        'has_solar_system': solar_system is not None,
        'has_battery': Battery.objects.filter(user=user).exists(),
        'has_grid_config': GridConfiguration.objects.filter(user=user).exists(),
        'solar_system': solar_system,
    }


def next_setup_step(user):
    status = setup_status(user)
    if not status['has_location']:
        return 'solar:setup_location'
    if not status['has_solar_system']:
        return 'solar:setup_system'
    system = status['solar_system']
    if system.needs_battery and not status['has_battery']:
        return 'solar:setup_battery'
    if system.needs_grid_config and not status['has_grid_config']:
        return 'solar:setup_grid'
    return None


def setup_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('accounts:login')
        step = next_setup_step(request.user)
        if step:
            return redirect(step)
        return view_func(request, *args, **kwargs)
    return wrapper