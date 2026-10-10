from datetime import date
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from forecast import prediction_service as ps
from forecast.prediction_service import PredictionError, predict_generation, build_feature_frame

# Weather for 12-14 Sep 2026 and the predictions the model produced in the
# Colab unseen-data test. If the model, scikit-learn version or feature order
# changes, these tests fail.
KNOWN_DAYS = [
    ("2026-09-12", {"Temperature_C": 28.2, "Humidity_%": 78, "WindSpeed_mps": 2.40,
                    "Solar_Irradiance_kWhm2": 6.397222, "Rainfall_mm": 0.4}, 16.819),
    ("2026-09-13", {"Temperature_C": 28.5, "Humidity_%": 75, "WindSpeed_mps": 2.20,
                    "Solar_Irradiance_kWhm2": 6.266667, "Rainfall_mm": 0.5}, 16.735),
    ("2026-09-14", {"Temperature_C": 28.1, "Humidity_%": 77, "WindSpeed_mps": 2.21,
                    "Solar_Irradiance_kWhm2": 5.811111, "Rainfall_mm": 4.5}, 16.076),
]


class FakeModel:
    def __init__(self, value):
        self.value = value

    def predict(self, frame):
        return [self.value]


class PredictionServiceTests(SimpleTestCase):
    def setUp(self):
        ps._model = None  # force a fresh load for each test

    def test_matches_colab_results_for_known_days(self):
        for day, weather, expected in KNOWN_DAYS:
            with self.subTest(day=day):
                self.assertAlmostEqual(predict_generation(weather, day), expected, delta=0.01)

    def test_ignores_extra_keys_like_date(self):
        _, weather, expected = KNOWN_DAYS[0]
        result = predict_generation({**weather, "date": "2026-09-12"}, "2026-09-12")
        self.assertAlmostEqual(result, expected, delta=0.01)

    def test_day_of_year_derived_from_date(self):
        _, weather, _ = KNOWN_DAYS[0]
        frame = build_feature_frame(weather, date(2026, 9, 12))
        self.assertEqual(int(frame["Day_of_Year"].iloc[0]), 255)

    def test_frame_columns_follow_configured_order(self):
        _, weather, _ = KNOWN_DAYS[0]
        frame = build_feature_frame(weather, "2026-09-12")
        self.assertEqual(list(frame.columns), [
            "Temperature_C", "Humidity_%", "WindSpeed_mps",
            "Solar_Irradiance_kWhm2", "Rainfall_mm", "Day_of_Year"])

    def test_missing_feature_raises(self):
        _, weather, _ = KNOWN_DAYS[0]
        weather = {k: v for k, v in weather.items() if k != "Humidity_%"}
        with self.assertRaisesMessage(PredictionError, "Humidity_%"):
            predict_generation(weather, "2026-09-12")

    def test_none_value_raises(self):
        _, weather, _ = KNOWN_DAYS[0]
        with self.assertRaises(PredictionError):
            predict_generation({**weather, "Rainfall_mm": None}, "2026-09-12")

    def test_negative_prediction_is_clipped_to_zero(self):
        _, weather, _ = KNOWN_DAYS[0]
        with patch.object(ps, "load_model", return_value=FakeModel(-3.7)):
            self.assertEqual(predict_generation(weather, "2026-09-12"), 0.0)

    def test_missing_model_file_raises_friendly_error(self):
        from pathlib import Path
        with override_settings(ML_MODEL_PATH=Path("/nonexistent/model.pkl")):
            with self.assertRaisesMessage(PredictionError, "not found"):
                ps.load_model()

    def test_feature_mismatch_with_model_raises(self):
        _, weather, _ = KNOWN_DAYS[0]
        wrong_order = ["Humidity_%", "Temperature_C", "WindSpeed_mps",
                       "Solar_Irradiance_kWhm2", "Rainfall_mm", "Day_of_Year"]
        with override_settings(MODEL_FEATURES=wrong_order):
            with self.assertRaisesMessage(PredictionError, "mismatch"):
                predict_generation(weather, "2026-09-12")

        # --- Capacity scaling (enabled in settings; pinned explicitly here) ---

    @override_settings(PREDICTION_SCALE_BY_CAPACITY=True, MODEL_REFERENCE_CAPACITY_KW=3.0)
    def test_scaling_doubles_output_for_double_capacity(self):
        _, weather, expected = KNOWN_DAYS[0]
        result = predict_generation(weather, "2026-09-12", capacity_kw=6)
        self.assertAlmostEqual(result, expected * 2, delta=0.02)

    @override_settings(PREDICTION_SCALE_BY_CAPACITY=True, MODEL_REFERENCE_CAPACITY_KW=3.0)
    def test_scaling_leaves_reference_capacity_unchanged(self):
        _, weather, expected = KNOWN_DAYS[0]
        result = predict_generation(weather, "2026-09-12", capacity_kw=3)
        self.assertAlmostEqual(result, expected, delta=0.01)

    @override_settings(PREDICTION_SCALE_BY_CAPACITY=True, MODEL_REFERENCE_CAPACITY_KW=3.0)
    def test_scaling_reduces_output_for_smaller_system(self):
        _, weather, expected = KNOWN_DAYS[0]
        result = predict_generation(weather, "2026-09-12", capacity_kw=1.5)
        self.assertAlmostEqual(result, expected / 2, delta=0.02)

    @override_settings(PREDICTION_SCALE_BY_CAPACITY=True, MODEL_REFERENCE_CAPACITY_KW=3.0)
    def test_no_capacity_means_no_scaling(self):
        _, weather, expected = KNOWN_DAYS[0]
        self.assertAlmostEqual(predict_generation(weather, "2026-09-12"), expected, delta=0.01)

    @override_settings(PREDICTION_SCALE_BY_CAPACITY=False)
    def test_scaling_can_be_switched_off(self):
        _, weather, expected = KNOWN_DAYS[0]
        result = predict_generation(weather, "2026-09-12", capacity_kw=6)
        self.assertAlmostEqual(result, expected, delta=0.01)

    @override_settings(PREDICTION_SCALE_BY_CAPACITY=True, MODEL_REFERENCE_CAPACITY_KW=3.0)
    def test_scaled_negative_prediction_still_zero(self):
        _, weather, _ = KNOWN_DAYS[0]
        with patch.object(ps, "load_model", return_value=FakeModel(-3.7)):
            self.assertEqual(predict_generation(weather, "2026-09-12", capacity_kw=6), 0.0)