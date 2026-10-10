"""
ML inference layer. Loads the externally trained Random Forest and turns a
weather-feature dictionary into a predicted daily generation (kWh).

Integration only: this module never trains, tunes or modifies the model.
It is also deliberately independent of Open-Meteo and of the database, so it
can be tested on its own with a plain dictionary.
"""
import logging
import warnings
from datetime import date

import joblib
import pandas as pd
from django.conf import settings

logger = logging.getLogger(__name__)

_model = None  # loaded once per server process, then reused


class PredictionError(Exception):
    """Raised for any recoverable inference problem (missing model file,
    feature mismatch, bad input). Views catch this and show a friendly
    message instead of crashing."""
    pass


def load_model():
    """Load the saved model once and cache it in memory."""
    global _model
    if _model is not None:
        return _model

    path = settings.ML_MODEL_PATH
    if not path.exists():
        raise PredictionError(
            f"Prediction model file not found at {path}. "
            "Place the trained model file in the ml_models folder."
        )

    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            model = joblib.load(path)
    except Exception as exc:
        logger.exception("Could not load ML model from %s", path)
        raise PredictionError(
            "The prediction model could not be loaded. This usually means the installed "
            "scikit-learn version differs from the one the model was saved with."
        ) from exc

    for w in caught:
        logger.warning("While loading the ML model: %s", w.message)

    # The model remembers the column names/order it was trained with. If our
    # central configuration disagrees, fail loudly instead of predicting garbage.
    trained_features = getattr(model, "feature_names_in_", None)
    if trained_features is not None and list(trained_features) != list(settings.MODEL_FEATURES):
        raise PredictionError(
            f"Model/feature mismatch. Model was trained on {list(trained_features)} "
            f"but settings.MODEL_FEATURES is {list(settings.MODEL_FEATURES)}."
        )

    _model = model
    return _model


def build_feature_frame(weather, prediction_date):
    """
    Builds the one-row DataFrame the model expects: exact trained column
    names, exact trained order. Day_of_Year is derived from the prediction
    date here, because it is a property of the date, not of the weather.
    """
    if isinstance(prediction_date, str):
        prediction_date = date.fromisoformat(prediction_date)

    values = dict(weather)
    values["Day_of_Year"] = prediction_date.timetuple().tm_yday

    missing = [f for f in settings.MODEL_FEATURES if values.get(f) is None]
    if missing:
        raise PredictionError(f"Missing required model inputs: {', '.join(missing)}")

    try:
        row = [float(values[f]) for f in settings.MODEL_FEATURES]
    except (TypeError, ValueError) as exc:
        raise PredictionError("A model input was not a valid number.") from exc

    return pd.DataFrame([row], columns=list(settings.MODEL_FEATURES))


def predict_generation(weather, prediction_date, capacity_kw=None):
    """
    Returns predicted next-day generation in kWh (never negative).

    `weather` is the dictionary from forecast.services (keys Temperature_C,
    Humidity_%, WindSpeed_mps, Solar_Irradiance_kWhm2, Rainfall_mm; extra keys
    such as 'date' are ignored).
    """
    model = load_model()
    frame = build_feature_frame(weather, prediction_date)

    try:
        raw = float(model.predict(frame)[0])
    except Exception as exc:
        logger.exception("Model inference failed")
        raise PredictionError("The prediction model failed to run on this input.") from exc

    kwh = max(0.0, raw)  # a negative generation figure is not a valid result

    # Capacity scaling is OFF unless explicitly enabled, because the model is
    # not known to predict a per-kW yield. See settings.PREDICTION_SCALE_BY_CAPACITY.
    if settings.PREDICTION_SCALE_BY_CAPACITY and capacity_kw:
        kwh *= capacity_kw / settings.MODEL_REFERENCE_CAPACITY_KW

    return round(kwh, 2)