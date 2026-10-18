"""Presentation helper for the dashboard's "Current weather" card (no database access)."""

# (keywords found in the condition text, icon, label, level 0-100, short explanation)
# Order matters: the first match wins, so more specific phrases come first.
_RULES = [
    (('thunder', 'storm'), 'bi-cloud-lightning-rain-fill', 'Poor', 10,
     'Stormy skies: expect very little solar generation.'),
    (('snow',), 'bi-cloud-snow-fill', 'Poor', 10,
     'Snow cover: expect very little solar generation.'),
    (('rain', 'drizzle', 'shower'), 'bi-cloud-rain-heavy-fill', 'Poor', 20,
     'Rain and thick cloud: generation will be low.'),
    (('fog', 'mist', 'haze'), 'bi-cloud-fog2-fill', 'Fair', 35,
     'Hazy sunlight: output will be reduced.'),
    (('overcast',), 'bi-clouds-fill', 'Fair', 40,
     'Heavy cloud: limited sunlight, so reduced generation.'),
    (('partly', 'mainly clear', 'few cloud'), 'bi-cloud-sun-fill', 'Good', 70,
     'Some cloud, but solar output should still be decent.'),
    (('cloud',), 'bi-cloud-fill', 'Fair', 45,
     'Cloudy: sunlight is limited, so expect reduced generation.'),
    (('clear', 'sun'), 'bi-sun-fill', 'Excellent', 92,
     'Strong sunshine: panels should be near their best output.'),
]

_RAIN_LIMIT_MM = 0.5     # this much rain or more caps the outlook at "Poor"


def _field(weather, name, default=None):
    """Read a value from either a dict or a model/object."""
    if isinstance(weather, dict):
        return weather.get(name, default)
    return getattr(weather, name, default)


def describe_weather(weather):
    """
    Turn current weather (a dict or a WeatherData record) into display hints:
        icon     Bootstrap icon class for the condition
        label    "Excellent" / "Good" / "Fair" / "Poor", or "" if the condition isn't recognised
        level    0-100, for the meter (0 when unknown)
        tone     excellent / good / fair / poor / unknown (a CSS class suffix)
        note     one short sentence about what it means for solar
    This is a simple reading of the current conditions, not an ML result.
    Returns None when there is no weather.
    """
    if not weather:
        return None
    text = (_field(weather, 'condition') or '').lower()
    rain = _field(weather, 'rainfall_mm') or 0
    icon, label, level, note = 'bi-cloud-sun-fill', '', 0, ''
    for keywords, r_icon, r_label, r_level, r_note in _RULES:
        if any(k in text for k in keywords):
            icon, label, level, note = r_icon, r_label, r_level, r_note
            break
    if label and rain >= _RAIN_LIMIT_MM and label != 'Poor':
        label, level, note = 'Poor', min(level, 25), 'Rain is falling: generation will be low.'
    return {'icon': icon, 'label': label, 'level': level,
            'tone': label.lower() if label else 'unknown', 'note': note}