import logging

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from decision_support.models import Recommendation
from decision_support.services import refresh_open_recommendations
from forecast.models import Prediction
from solar.models import Appliance, Battery, GridConfiguration, SolarSystem

from .decorators import staff_required
from .forms import (AdminRecommendationFilterForm, ApplianceFilterForm, PredictionFilterForm,
                    SystemFilterForm, UserFilterForm)
from .services import (customer_appliances, customer_predictions, customer_recommendations,
                       customer_systems, customers, deletion_summary, overview_stats,
                       search_appliances, search_customers, search_predictions,
                       search_recommendations, search_systems)

logger = logging.getLogger(__name__)
PAGE_SIZE = 10


def _querystring(request):
    """Current filters without the page number, so pagination links keep them."""
    params = request.GET.copy()
    params.pop('page', None)
    return params.urlencode()


def _safe_next(request, fallback):
    """Where to go back to after an action; ignores anything that points off-site."""
    target = request.POST.get('next') or request.GET.get('next')
    if target and url_has_allowed_host_and_scheme(
            target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return target
    return fallback


def _refresh_owner_advice(request, owner):
    """The owner's appliance list changed, so rebuild their recommendations (never raises)."""
    if refresh_open_recommendations(owner):
        messages.info(request, f"{owner.username}'s recommendations were updated to match this change.")


@staff_required
def overview(request):
    return render(request, 'adminpanel/overview.html', {
        'stats': overview_stats(),
        'active': 'overview',
    })


# ------------------------------------------------------------------- users
@staff_required
def user_list(request):
    form = UserFilterForm(request.GET or None)
    cleaned = form.cleaned_data if form.is_valid() else {}
    qs = search_customers(cleaned.get('q', ''), cleaned.get('status', ''))
    page = Paginator(qs, PAGE_SIZE).get_page(request.GET.get('page'))
    return render(request, 'adminpanel/users.html', {
        'form': form, 'page': page, 'querystring': _querystring(request), 'active': 'users',
    })


@staff_required
@require_GET
def user_detail(request, pk):
    target = get_object_or_404(customers(), pk=pk)
    return render(request, 'adminpanel/user_detail.html', {
        'target': target,           # not "user": base.html already uses that name for the logged-in admin
        'system': SolarSystem.objects.filter(user=target).first(),
        'appliance_count': Appliance.objects.filter(user=target).count(),
        'prediction_count': Prediction.objects.filter(user=target).count(),
        'recommendation_count': Recommendation.objects.filter(user=target).count(),
        'active': 'users',
    })


@staff_required
@require_POST
def user_toggle_active(request, pk):
    target = get_object_or_404(customers(), pk=pk)
    target.is_active = not target.is_active
    target.save(update_fields=['is_active'])
    verb = 'activated' if target.is_active else 'deactivated'
    logger.info("Admin %s %s user %s", request.user.username, verb, target.username)
    messages.success(request, f"{target.username} was {verb}.")
    return redirect('adminpanel:user_detail', pk=target.pk)


@staff_required
@require_http_methods(['GET', 'POST'])
def user_delete(request, pk):
    target = get_object_or_404(customers(), pk=pk)
    if request.method == 'POST':
        name = target.username
        target.delete()
        logger.info("Admin %s deleted user %s", request.user.username, name)
        messages.success(request, f"{name} and all their data were deleted.")
        return redirect('adminpanel:users')
    return render(request, 'adminpanel/user_confirm_delete.html', {
        'target': target, 'summary': deletion_summary(target), 'active': 'users',
    })


# ----------------------------------------------------------------- systems
@staff_required
def system_list(request):
    form = SystemFilterForm(request.GET or None)
    cleaned = form.cleaned_data if form.is_valid() else {}
    qs = search_systems(cleaned.get('q', ''), cleaned.get('system_type', ''))
    page = Paginator(qs, PAGE_SIZE).get_page(request.GET.get('page'))
    return render(request, 'adminpanel/systems.html', {
        'form': form, 'page': page, 'querystring': _querystring(request), 'active': 'systems',
    })


@staff_required
@require_GET
def system_detail(request, pk):
    system = get_object_or_404(customer_systems(), pk=pk)
    owner = system.user
    return render(request, 'adminpanel/system_detail.html', {
        'system': system,
        'owner': owner,
        'battery': Battery.objects.filter(user=owner).first(),
        'grid': GridConfiguration.objects.filter(user=owner).first(),
        'appliance_count': Appliance.objects.filter(user=owner).count(),
        'latest_prediction': Prediction.objects.filter(user=owner).order_by('-prediction_for_date').first(),
        'active': 'systems',
    })


# -------------------------------------------------------------- appliances
@staff_required
def appliance_list(request):
    form = ApplianceFilterForm(request.GET or None)
    cleaned = form.cleaned_data if form.is_valid() else {}
    owner = customers().filter(pk=cleaned['user']).first() if cleaned.get('user') else None
    qs = search_appliances(
        q=cleaned.get('q', ''), priority=cleaned.get('priority', ''),
        status=cleaned.get('status', ''), user_id=owner.pk if owner else None)
    page = Paginator(qs, PAGE_SIZE).get_page(request.GET.get('page'))
    return render(request, 'adminpanel/appliances.html', {
        'form': form, 'page': page, 'owner': owner, 'querystring': _querystring(request),
        'current_path': request.get_full_path(), 'active': 'appliances',
    })


@staff_required
@require_POST
def appliance_toggle(request, pk):
    appliance = get_object_or_404(customer_appliances(), pk=pk)
    appliance.is_active = not appliance.is_active
    appliance.save(update_fields=['is_active'])
    verb = 'activated' if appliance.is_active else 'deactivated'
    logger.info("Admin %s %s appliance %s (owner %s)", request.user.username, verb,
                appliance.name, appliance.user.username)
    messages.success(request, f"{appliance.name} ({appliance.user.username}) was {verb}.")
    _refresh_owner_advice(request, appliance.user)
    return redirect(_safe_next(request, reverse('adminpanel:appliances')))


@staff_required
@require_http_methods(['GET', 'POST'])
def appliance_delete(request, pk):
    appliance = get_object_or_404(customer_appliances(), pk=pk)
    back = _safe_next(request, reverse('adminpanel:appliances'))
    if request.method == 'POST':
        owner, name = appliance.user, appliance.name
        appliance.delete()
        logger.info("Admin %s deleted appliance %s (owner %s)", request.user.username, name, owner.username)
        messages.success(request, f"{name} ({owner.username}) was deleted.")
        _refresh_owner_advice(request, owner)
        return redirect(back)
    return render(request, 'adminpanel/appliance_confirm_delete.html', {
        'appliance': appliance, 'next': back, 'active': 'appliances',
    })


# ------------------------------------------------------------- predictions
@staff_required
def prediction_list(request):
    form = PredictionFilterForm(request.GET or None)
    cleaned = form.cleaned_data if form.is_valid() else {}
    owner = customers().filter(pk=cleaned['user']).first() if cleaned.get('user') else None
    qs = search_predictions(
        q=cleaned.get('q', ''), date_from=cleaned.get('date_from'), date_to=cleaned.get('date_to'),
        user_id=owner.pk if owner else None)
    page = Paginator(qs, PAGE_SIZE).get_page(request.GET.get('page'))
    return render(request, 'adminpanel/predictions.html', {
        'form': form, 'page': page, 'owner': owner, 'querystring': _querystring(request),
        'current_path': request.get_full_path(), 'active': 'predictions',
    })


@staff_required
@require_http_methods(['GET', 'POST'])
def prediction_delete(request, pk):
    prediction = get_object_or_404(customer_predictions(), pk=pk)
    back = _safe_next(request, reverse('adminpanel:predictions'))
    if request.method == 'POST':
        owner, day = prediction.user, prediction.prediction_for_date
        prediction.delete()
        logger.info("Admin %s deleted the %s prediction of %s", request.user.username, day, owner.username)
        messages.success(request, f"Prediction for {day:%d %b %Y} ({owner.username}) was deleted.")
        return redirect(back)
    return render(request, 'adminpanel/prediction_confirm_delete.html', {
        'prediction': prediction, 'next': back, 'active': 'predictions',
    })


# --------------------------------------------------------- recommendations
@staff_required
def recommendation_list(request):
    form = AdminRecommendationFilterForm(request.GET or None)
    cleaned = form.cleaned_data if form.is_valid() else {}
    owner = customers().filter(pk=cleaned['user']).first() if cleaned.get('user') else None
    qs = search_recommendations(
        q=cleaned.get('q', ''), recommendation_type=cleaned.get('recommendation_type', ''),
        priority=cleaned.get('priority', ''), date_from=cleaned.get('date_from'),
        date_to=cleaned.get('date_to'), user_id=owner.pk if owner else None)
    page = Paginator(qs, PAGE_SIZE).get_page(request.GET.get('page'))
    return render(request, 'adminpanel/recommendations.html', {
        'form': form, 'page': page, 'owner': owner, 'querystring': _querystring(request),
        'current_path': request.get_full_path(), 'today': timezone.localdate(),
        'currency': getattr(settings, 'CURRENCY_SYMBOL', ''), 'active': 'recommendations',
    })


@staff_required
@require_http_methods(['GET', 'POST'])
def recommendation_delete(request, pk):
    rec = get_object_or_404(customer_recommendations(), pk=pk)
    back = _safe_next(request, reverse('adminpanel:recommendations'))
    if rec.prediction.prediction_for_date >= timezone.localdate():
        # Today's and upcoming advice is rebuilt automatically; removing single tips would leave gaps.
        messages.error(request, "Only past recommendations can be deleted. Today's and upcoming advice stays "
                                "so the customer is never left without it; delete the prediction instead "
                                "to clear a whole day.")
        return redirect(back)
    if request.method == 'POST':
        owner, title = rec.user, rec.title
        rec.delete()
        logger.info("Admin %s deleted recommendation '%s' (owner %s)", request.user.username, title, owner.username)
        messages.success(request, f"Recommendation “{title}” ({owner.username}) was deleted.")
        return redirect(back)
    return render(request, 'adminpanel/recommendation_confirm_delete.html', {
        'rec': rec, 'next': back, 'active': 'recommendations',
    })