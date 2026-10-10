import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from decision_support.services import DecisionSupportError, generate_recommendations
from solar.decorators import setup_required
from .models import Prediction
from .prediction_service import PredictionError
from .services import WeatherServiceError
from .workflow import generate_tomorrow_prediction

logger = logging.getLogger(__name__)


@login_required
@setup_required
@require_POST
def generate_prediction(request):
    try:
        prediction, created = generate_tomorrow_prediction(request.user)
    except WeatherServiceError as exc:
        messages.error(request, str(exc))
    except PredictionError as exc:
        messages.error(request, f"Could not generate the prediction: {exc}")
    except Exception:
        logger.exception("Unexpected error while generating a prediction")
        messages.error(request, "Something went wrong while generating the prediction. Please try again.")
    else:
        verb = "generated" if created else "updated"
        text = (f"Prediction {verb}: {prediction.predicted_generation_kwh} kWh expected on "
                f"{prediction.prediction_for_date:%d %b %Y}.")
        # Prediction (ML) is finished and saved. Now hand it to the DSS, which is a separate module.
        # A DSS problem must never undo or hide a successful prediction.
        try:
            count = len(generate_recommendations(request.user, prediction))
            text += f" {count} recommendation{'s' if count != 1 else ''} ready."
            messages.success(request, text)
        except DecisionSupportError as exc:
            messages.success(request, text)
            messages.warning(request, str(exc))
        except Exception:
            logger.exception("Unexpected error while generating recommendations")
            messages.success(request, text)
            messages.warning(request, "The prediction was saved, but recommendations could not be generated.")
    return redirect('dashboard:home')


@login_required
@setup_required
def prediction_history(request):
    qs = Prediction.objects.filter(user=request.user).select_related('weather_data')
    page = Paginator(qs, 10).get_page(request.GET.get('page'))

    recent = list(qs[:14])[::-1]                       # oldest -> newest for the chart
    chart = {
        'labels': [p.prediction_for_date.strftime('%d %b') for p in recent],
        'values': [p.predicted_generation_kwh for p in recent],
    }
    return render(request, 'forecast/prediction_history.html', {'page': page, 'chart': chart})
