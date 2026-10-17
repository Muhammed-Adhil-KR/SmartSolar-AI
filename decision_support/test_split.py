from django.test import TestCase

from decision_support.services import energy_split
from decision_support.tests import add_appliance, make_prediction, make_user


class EnergySplitTests(TestCase):
    def test_none_without_prediction(self):
        user = make_user()
        self.assertIsNone(energy_split(user, None))

    def test_none_without_appliances(self):
        user = make_user()
        self.assertIsNone(energy_split(user, make_prediction(user, 10)))

    def test_partial_coverage_hybrid(self):
        user = make_user('HYBRID')
        add_appliance(user, 'Heater', 1000, 10)       # 10 kWh demand
        split = energy_split(user, make_prediction(user, 4))
        self.assertEqual(split['solar_pct'], 40)
        self.assertEqual(split['other_pct'], 60)
        self.assertEqual(split['other_label'], 'Battery + grid')
        self.assertEqual(split['spare_kwh'], 0)

    def test_surplus_fills_the_bar(self):
        user = make_user('ON_GRID')
        add_appliance(user, 'Fan', 1000, 5)           # 5 kWh demand
        split = energy_split(user, make_prediction(user, 8))
        self.assertEqual(split['solar_pct'], 100)
        self.assertEqual(split['other_pct'], 0)
        self.assertEqual(split['other_label'], 'Grid')
        self.assertEqual(split['spare_kwh'], 3.0)
        self.assertEqual(split['coverage_pct'], 160)

    def test_off_grid_label_and_unmet(self):
        user = make_user('OFF_GRID', soc=20)           # battery at its minimum: nothing usable
        add_appliance(user, 'Pump', 1000, 6)
        split = energy_split(user, make_prediction(user, 2))
        self.assertEqual(split['other_label'], 'Battery')
        self.assertGreater(split['unmet_kwh'], 0)