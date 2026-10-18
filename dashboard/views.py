import logging

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.shortcuts import render
from datetime import date, timedelta
from forecast.models import Prediction

from forecast.services import (
    WeatherServiceError,
    get_or_fetch_current_weather,
    get_or_fetch_tomorrow_forecast,
)
from solar.decorators import setup_required
from solar.models import Appliance, Battery
from decision_support.services import dashboard_recommendations, energy_split
from .weather_view import describe_weather

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CONTACT DETAILS shown in the "About & Contact" section of the Home page.
#
# >>> PUT YOUR OWN DETAILS HERE. This is the only place to edit. <<<
# Set any value to "" and that line is hidden on the page.
# ---------------------------------------------------------------------------
CONTACT = {
    'name': 'Adhil',
    # 'role': 'MCA Mini Project',
    'email': 'adhil@example.com',
    # 'course': 'MCA, Your Department',
    # 'college': 'Your College Name',
}

# Static page content (kept here so the template stays simple).
HOW_IT_WORKS = [
    (1, 'bi-person-plus', 'Create your account', 'Register and log in. It only takes a minute.'),
    (2, 'bi-sun', 'Describe your system', 'Add your location, system size, and battery or grid details if you have them.'),
    (3, 'bi-plug', 'Add your appliances', 'List what you use, how long, and how important each one is.'),
    (4, 'bi-lightbulb', "Get tomorrow's plan", 'Generate the forecast and read clear advice on how to use your power.'),
]

FEATURES = [
    ('bi-graph-up-arrow', False, 'Solar forecast', "A machine-learning model estimates tomorrow's generation from the weather at your location, scaled to your system size."),
    ('bi-lightbulb', True, 'Smart recommendations', 'Rule-based advice on when to run appliances, when to charge or save the battery, and how to use the grid.'),
    ('bi-plug', False, 'Appliance priorities', 'Mark essentials as critical or high priority. They are protected first, and flexible loads are moved to sunny hours.'),
    ('bi-cloud-sun', True, 'Live weather', 'See current conditions and a short forecast for your exact location.'),
    ('bi-battery-charging', False, 'Battery and grid aware', 'Advice changes with your system type, your battery level and your grid setup.'),
    ('bi-clock-history', True, 'History', 'Look back at earlier predictions and recommendations, filtered by date, type or priority.'),
]

FAQS = [
    ('How accurate are the predictions?',
     'They are estimates. The model learns from weather patterns, but real generation also depends on shading, dust, panel condition and sudden weather changes.'),
    ('Do I need a battery or a grid connection?',
     'No. During setup you choose on-grid, off-grid or hybrid, and only the details that apply to you are asked.'),
    ('Why do I have to click to generate a prediction?',
     'Predictions are generated when you ask, so you always know exactly which day and which system size the numbers are for.'),
    ('What happens if I change my location or system size?',
     'Old predictions and advice that no longer match are cleared, and you can generate fresh ones.'),
    ('Does SmartSolar control my appliances?',
     'No. It only gives advice. You decide what to switch on or off.'),
]


def landing(request):
    """Public Home page. Visible to everyone; the buttons change if logged in."""
    return render(request, 'dashboard/landing.html', {
        'contact': CONTACT, 'steps': HOW_IT_WORKS, 'features': FEATURES, 'faqs': FAQS,
    })


@login_required
@setup_required
def home(request):
    user = request.user
    system = user.solarsystem  # guaranteed by @setup_required

    # --- Weather cards: each is isolated, so one failure never breaks the page ---
    current_weather, current_error = None, None
    try:
        current_weather = get_or_fetch_current_weather(user)
    except WeatherServiceError as exc:
        current_error = str(exc)
    except Exception:
        logger.exception("Unexpected error fetching current weather")
        current_error = "Current weather is temporarily unavailable."

    forecast, forecast_error = None, None
    try:
        forecast = get_or_fetch_tomorrow_forecast(user)
    except WeatherServiceError as exc:
        forecast_error = str(exc)
    except Exception:
        logger.exception("Unexpected error fetching tomorrow's forecast")
        forecast_error = "Tomorrow's forecast is temporarily unavailable."

    # --- System summary (battery/grid shown only if a record exists) ---
    battery = Battery.objects.filter(user=user).first()
    

    # --- Appliance summary ---
    active = Appliance.objects.filter(user=user, is_active=True)
    totals = active.aggregate(total_energy=Sum('daily_energy_kwh'), count=Count('id'))
    appliance_summary = {
        'active_count': totals['count'] or 0,
        'total_energy': round(totals['total_energy'] or 0, 2),
        'shiftable_count': active.filter(is_shiftable=True).count(),
        'inactive_count': Appliance.objects.filter(user=user, is_active=False).count(),
    }
    tomorrow = date.today() + timedelta(days=1)
    prediction = Prediction.objects.filter(user=request.user, prediction_for_date=tomorrow).first()
    top_recs, rec_total = dashboard_recommendations(prediction)
    split = energy_split(request.user, prediction)

    return render(request, 'dashboard/home.html', {
        'system': system,
        'battery': battery,
        'current_weather': current_weather,
        'current_error': current_error,
        'forecast': forecast,
        'forecast_error': forecast_error,
        'appliance_summary': appliance_summary,
        'prediction': prediction, 
        'tomorrow': tomorrow,
        'top_recs': top_recs, 
        'rec_total': rec_total,
        'split': split,
        'weather_info': describe_weather(current_weather),
    })