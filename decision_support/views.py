import logging
from datetime import date, timedelta
from itertools import groupby

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from solar.decorators import setup_required
from .forms import RecommendationFilterForm
from .models import Recommendation
from .services import (
    DecisionSupportError, generate_recommendations, summary_tiles, tomorrows_prediction)

logger = logging.getLogger(__name__)

DAYS_PER_PAGE = 7


@login_required
@setup_required
def recommendations_tomorrow(request):
    prediction = tomorrows_prediction(request.user)
    recs, tiles = [], []
    if prediction:
        recs = list(Recommendation.objects.filter(prediction=prediction).select_related('appliance').by_priority())
        if recs:
            tiles = summary_tiles(request.user, prediction)
    return render(request, 'decision_support/recommendations.html', {
        'tomorrow': date.today() + timedelta(days=1),
        'prediction': prediction, 'recs': recs, 'tiles': tiles,
        'generated_at': recs[0].created_at if recs else None,
        'currency': settings.CURRENCY_SYMBOL,
    })


@login_required
@setup_required
@require_POST
def refresh_recommendations(request):
    """Re-run only the DSS for tomorrow's existing prediction (no ML, no forecast call)."""
    try:
        count = len(generate_recommendations(request.user))
    except DecisionSupportError as exc:
        messages.warning(request, str(exc))
    except Exception:
        logger.exception("Unexpected error while refreshing recommendations")
        messages.error(request, "Something went wrong while refreshing recommendations. Please try again.")
    else:
        messages.success(request, f"{count} recommendation{'s' if count != 1 else ''} refreshed.")
    if request.POST.get('next') == 'dashboard':
        return redirect('dashboard:home')
    return redirect('decision_support:current')


@login_required
@setup_required
def recommendation_history(request):
    form = RecommendationFilterForm(request.GET or None, system=request.user.solarsystem)
    qs = Recommendation.objects.filter(user=request.user)

    filtered = False
    if form.is_bound and form.is_valid():
        data = form.cleaned_data
        if data['recommendation_type']:
            qs = qs.filter(recommendation_type=data['recommendation_type'])
        if data['priority']:
            qs = qs.filter(priority=data['priority'])
        if data['date_from']:
            qs = qs.filter(prediction__prediction_for_date__gte=data['date_from'])
        if data['date_to']:
            qs = qs.filter(prediction__prediction_for_date__lte=data['date_to'])
        filtered = any(data.values())
    # An invalid form (bad date, From after To) shows its errors and leaves the list unfiltered.

    # Paginate by DAY: first the distinct dates that have matching recommendations...
    dates = (qs.order_by().values_list('prediction__prediction_for_date', flat=True)
             .distinct().order_by('-prediction__prediction_for_date'))
    page = Paginator(dates, DAYS_PER_PAGE).get_page(request.GET.get('page'))

    # ...then the recommendations for just those days, grouped.
    rows = list(qs.filter(prediction__prediction_for_date__in=list(page))
                .select_related('prediction', 'appliance').by_priority())
    rows.sort(key=lambda r: r.prediction.prediction_for_date, reverse=True)   # stable: keeps priority order
    days = [{'date': d, 'recs': list(group), 'top': None}
            for d, group in groupby(rows, key=lambda r: r.prediction.prediction_for_date)]
    for day in days:
        day['top'] = day['recs'][0]          # by_priority puts the most important first

    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'decision_support/history.html', {
        'form': form, 'days': days, 'page': page, 'filtered': filtered,
        'querystring': params.urlencode(), 'currency': settings.CURRENCY_SYMBOL,
    })