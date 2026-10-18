"""Advice follows the user's current settings; past days stay as history."""
from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from decision_support.models import Recommendation as Rec
from decision_support.services import generate_recommendations, refresh_open_recommendations
from decision_support.tests import WINDOW, add_appliance, make_prediction, make_user


class RefreshOpenRecommendationsTests(TestCase):
    def setUp(self):
        self.user = make_user('HYBRID')
        self.fan = add_appliance(self.user, 'Fan', 1000, 12)
        self.heater = add_appliance(self.user, 'Heater', 800, 2, 'MEDIUM', shiftable=True)
        self.today_pred = make_prediction(self.user, 7.0, on=date.today())
        self.tomorrow_pred = make_prediction(self.user, 9.0)
        self.past_pred = make_prediction(self.user, 8.0, on=date.today() - timedelta(days=3))
        for p in (self.today_pred, self.tomorrow_pred, self.past_pred):
            generate_recommendations(self.user, p, window=WINDOW)

    def ids(self, prediction):
        return set(Rec.objects.filter(prediction=prediction).values_list('id', flat=True))

    def test_deactivating_an_appliance_updates_open_days_only(self):
        self.assertTrue(Rec.objects.filter(prediction=self.tomorrow_pred, appliance=self.heater).exists())
        past_before = self.ids(self.past_pred)
        self.heater.is_active = False
        self.heater.save()
        written = refresh_open_recommendations(self.user, window=WINDOW)
        self.assertGreater(written, 0)
        for p in (self.today_pred, self.tomorrow_pred):
            self.assertFalse(Rec.objects.filter(prediction=p, appliance=self.heater).exists())
            self.assertTrue(Rec.objects.filter(prediction=p).exists())      # rebuilt, not emptied
        self.assertEqual(self.ids(self.past_pred), past_before)             # history untouched

    def test_activating_an_appliance_adds_its_advice(self):
        self.heater.is_active = False
        self.heater.save()
        refresh_open_recommendations(self.user, window=WINDOW)
        self.heater.is_active = True
        self.heater.save()
        refresh_open_recommendations(self.user, window=WINDOW)
        self.assertTrue(Rec.objects.filter(prediction=self.tomorrow_pred, appliance=self.heater).exists())

    def test_saving_settings_alone_never_deletes_advice(self):
        before_open = self.ids(self.tomorrow_pred) | self.ids(self.today_pred)
        before_past = self.ids(self.past_pred)
        add_appliance(self.user, 'Iron', 1000, 1)
        self.fan.average_usage_hours = 8
        self.fan.save()
        battery = self.user.battery
        battery.current_soc_percent = 80
        battery.save()
        grid = self.user.gridconfiguration
        grid.import_tariff_per_kwh = 9
        grid.save()
        system = self.user.solarsystem
        system.system_type = 'ON_GRID'
        system.save()
        self.fan.delete()
        self.assertEqual(self.ids(self.tomorrow_pred) | self.ids(self.today_pred), before_open)
        self.assertEqual(self.ids(self.past_pred), before_past)

    def test_no_system_or_no_prediction_is_a_quiet_zero(self):
        bare = User.objects.create_user('bare2', password='pw')
        self.assertEqual(refresh_open_recommendations(bare, window=WINDOW), 0)
        lonely = make_user('ON_GRID', name='lonely')
        self.assertEqual(refresh_open_recommendations(lonely, window=WINDOW), 0)

    def test_a_failure_never_raises(self):
        with patch('decision_support.services.generate_recommendations', side_effect=RuntimeError('boom')):
            with self.assertLogs('decision_support.services', level='ERROR'):
                self.assertEqual(refresh_open_recommendations(self.user, window=WINDOW), 0)

    def test_other_users_are_untouched(self):
        other = make_user('ON_GRID', name='other2')
        add_appliance(other, 'Fan', 1000, 5)
        other_pred = make_prediction(other, 8.0)
        generate_recommendations(other, other_pred, window=WINDOW)
        before = self.ids(other_pred)
        refresh_open_recommendations(self.user, window=WINDOW)
        self.assertEqual(self.ids(other_pred), before)