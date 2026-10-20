"""Cross-user queries for the admin panel. Views stay thin; everything here reads the database only.
All figures describe customers; staff accounts are counted separately and never mixed in."""
from datetime import timedelta

from django.contrib.auth.models import User
from django.db.models import Count, Exists, OuterRef, Q
from django.utils import timezone

from decision_support.models import Recommendation
from forecast.models import Prediction, WeatherData
from solar.models import Appliance, Battery, GridConfiguration, SolarSystem

CHART_DAYS = 14


def customers():
    """The only accounts the panel manages. Staff are deliberately excluded."""
    return User.objects.filter(is_staff=False)


def customer_appliances():
    return Appliance.objects.filter(user__is_staff=False).select_related('user')


def customer_systems():
    return SolarSystem.objects.filter(user__is_staff=False).select_related('user')


def customer_predictions():
    return Prediction.objects.filter(user__is_staff=False).select_related('user')


def customer_recommendations():
    return (Recommendation.objects.filter(user__is_staff=False)
            .select_related('user', 'prediction', 'appliance'))


# ---------------------------------------------------------------- overview
def _systems_by_type():
    labels = dict(SolarSystem._meta.get_field('system_type').choices)
    rows = (SolarSystem.objects.filter(user__is_staff=False)
            .values('system_type').annotate(n=Count('id')).order_by('system_type'))
    return [{'label': str(labels.get(r['system_type'], r['system_type'])), 'count': r['n']} for r in rows]


def _predictions_per_day(today):
    start = today - timedelta(days=CHART_DAYS - 1)
    rows = (Prediction.objects.filter(user__is_staff=False,
                                      prediction_for_date__gte=start, prediction_for_date__lte=today)
            .values('prediction_for_date').annotate(n=Count('id')))
    counts = {r['prediction_for_date']: r['n'] for r in rows}
    days = [start + timedelta(days=i) for i in range(CHART_DAYS)]
    return {'labels': [d.strftime('%d %b') for d in days], 'values': [counts.get(d, 0) for d in days]}


def overview_stats():
    now = timezone.now()
    today = timezone.localdate()
    people = customers()
    appliances = Appliance.objects.filter(user__is_staff=False)
    predictions = Prediction.objects.filter(user__is_staff=False)
    return {
        'users_total': people.count(),
        'users_active': people.filter(is_active=True).count(),
        'users_new_week': people.filter(date_joined__gte=now - timedelta(days=7)).count(),
        'staff_total': User.objects.filter(is_staff=True).count(),
        'systems_total': SolarSystem.objects.filter(user__is_staff=False).count(),
        'systems_by_type': _systems_by_type(),
        'appliances_total': appliances.count(),
        'appliances_active': appliances.filter(is_active=True).count(),
        'predictions_total': predictions.count(),
        'recommendations_total': Recommendation.objects.filter(prediction__user__is_staff=False).count(),
        'predictions_chart': _predictions_per_day(today),
        'recent_users': list(people.order_by('-date_joined')[:5]),
        'recent_predictions': list(predictions.select_related('user').order_by('-created_at')[:5]),
    }


# ------------------------------------------------------------------- users
def search_customers(q='', status=''):
    qs = (customers().select_related('solarsystem')
          .annotate(appliance_count=Count('appliances', distinct=True))
          .order_by('-date_joined'))
    q = (q or '').strip()
    if q:
        qs = qs.filter(Q(username__icontains=q) | Q(email__icontains=q)
                       | Q(first_name__icontains=q) | Q(last_name__icontains=q))
    if status == 'active':
        qs = qs.filter(is_active=True)
    elif status == 'inactive':
        qs = qs.filter(is_active=False)
    return qs


def deletion_summary(user):
    """What deleting this account would remove, for the confirm page."""
    return {
        'has_system': SolarSystem.objects.filter(user=user).exists(),
        'has_battery': Battery.objects.filter(user=user).exists(),
        'has_grid': GridConfiguration.objects.filter(user=user).exists(),
        'appliances': Appliance.objects.filter(user=user).count(),
        'weather': WeatherData.objects.filter(user=user).count(),
        'predictions': Prediction.objects.filter(user=user).count(),
        'recommendations': Recommendation.objects.filter(prediction__user=user).count(),
    }


# -------------------------------------------------------------- appliances
def search_appliances(q='', priority='', status='', user_id=None):
    qs = customer_appliances().order_by('user__username', 'name')
    q = (q or '').strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(category__icontains=q) | Q(user__username__icontains=q))
    if priority:
        qs = qs.filter(priority=priority)
    if status == 'active':
        qs = qs.filter(is_active=True)
    elif status == 'inactive':
        qs = qs.filter(is_active=False)
    if user_id:
        qs = qs.filter(user_id=user_id)
    return qs


# ----------------------------------------------------------------- systems
def search_systems(q='', system_type=''):
    qs = (customer_systems()
          .annotate(has_battery=Exists(Battery.objects.filter(user=OuterRef('user'))),
                    has_grid=Exists(GridConfiguration.objects.filter(user=OuterRef('user'))))
          .order_by('user__username'))
    q = (q or '').strip()
    if q:
        qs = qs.filter(Q(user__username__icontains=q) | Q(location_name__icontains=q))
    if system_type:
        qs = qs.filter(system_type=system_type)
    return qs


# ------------------------------------------------------------- predictions
def search_predictions(q='', date_from=None, date_to=None, user_id=None):
    qs = customer_predictions().order_by('-prediction_for_date', 'user__username')
    q = (q or '').strip()
    if q:
        qs = qs.filter(user__username__icontains=q)
    if date_from:
        qs = qs.filter(prediction_for_date__gte=date_from)
    if date_to:
        qs = qs.filter(prediction_for_date__lte=date_to)
    if user_id:
        qs = qs.filter(user_id=user_id)
    return qs


# --------------------------------------------------------- recommendations
def search_recommendations(q='', recommendation_type='', priority='', date_from=None, date_to=None, user_id=None):
    """Newest day first, then owner, then most important first (same priority order the customers see)."""
    qs = (customer_recommendations().by_priority()
          .order_by('-prediction__prediction_for_date', 'user__username', 'priority_rank', 'id'))
    q = (q or '').strip()
    if q:
        qs = qs.filter(Q(user__username__icontains=q) | Q(title__icontains=q))
    if recommendation_type:
        qs = qs.filter(recommendation_type=recommendation_type)
    if priority:
        qs = qs.filter(priority=priority)
    if date_from:
        qs = qs.filter(prediction__prediction_for_date__gte=date_from)
    if date_to:
        qs = qs.filter(prediction__prediction_for_date__lte=date_to)
    if user_id:
        qs = qs.filter(user_id=user_id)
    return qs