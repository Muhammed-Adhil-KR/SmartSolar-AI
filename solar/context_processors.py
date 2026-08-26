def solar_context(request):
    """
    Injects the logged-in user's SolarSystem into every template's context,
    so templates can conditionally show/hide battery/grid sections without
    every view having to pass it in manually.
    """
    if request.user.is_authenticated and hasattr(request.user, 'solarsystem'):
        return {'user_solar_system': request.user.solarsystem}
    return {}