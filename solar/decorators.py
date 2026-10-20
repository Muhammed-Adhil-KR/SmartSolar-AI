"""
Central place that defines what "setup complete" means for a user,
so this logic is never duplicated across views.
"""
from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect

from .models import SolarSystem, Battery, GridConfiguration


def setup_status(user):
    solar_system = SolarSystem.objects.filter(user=user).first()
    return {
        'has_solar_system': solar_system is not None,
        'has_location': bool(solar_system and solar_system.has_location),
        'has_battery': Battery.objects.filter(user=user).exists(),
        'has_grid_config': GridConfiguration.objects.filter(user=user).exists(),
        'solar_system': solar_system,
    }


def next_setup_step(user):
    status = setup_status(user)
    if not status['has_solar_system']:
        return 'solar:setup_system'
    if not status['has_location']:
        return 'solar:setup_location'
    system = status['solar_system']
    if system.needs_battery and not status['has_battery']:
        return 'solar:setup_battery'
    if system.needs_grid_config and not status['has_grid_config']:
        return 'solar:setup_grid'
    return None


def customer_required(view_func):
    """Like login_required, but administrators are sent to the admin panel (they have no solar setup)."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if request.user.is_staff:
            return redirect('adminpanel:overview')
        return view_func(request, *args, **kwargs)
    return wrapper


def setup_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('accounts:login')
        # Administrators have no solar setup of their own: customer pages send them to the admin panel.
        if request.user.is_staff:
            return redirect('adminpanel:overview')
        step = next_setup_step(request.user)
        if step:
            return redirect(step)
        return view_func(request, *args, **kwargs)
    return wrapper