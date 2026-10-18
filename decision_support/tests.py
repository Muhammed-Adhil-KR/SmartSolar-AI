from datetime import date, time, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from django.conf import settings

import requests
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, override_settings

from decision_support.models import Recommendation as Rec
from decision_support.services import (
    DecisionSupportError, compute_balance, generate_recommendations)
from forecast.models import Prediction
from forecast.solar_window import SolarWindow, compute_window, default_window, get_solar_window
from solar.models import Appliance, Battery, GridConfiguration, SolarSystem

TOMORROW = date.today() + timedelta(days=1)
WINDOW = SolarWindow(9, 16, 'hourly', 800.0, False)


# ------------------------------------------------------------ solar window

class ComputeWindowTests(SimpleTestCase):
    def test_longest_run_above_half_of_peak(self):
        hourly = [0] * 6 + [50, 150, 300, 500, 700, 800, 780, 700, 500, 300, 100, 20, 0] + [0] * 5
        w = compute_window(hourly)
        self.assertEqual((w.start_hour, w.end_hour), (9, 15))       # 500..500 are >= 400
        self.assertEqual(w.source, 'hourly')
        self.assertFalse(w.weak)

    def test_cloudy_day_gives_narrower_window(self):
        hourly = [0] * 7 + [100, 200, 300, 250, 900, 280, 200, 150, 100, 0, 0] + [0] * 6
        w = compute_window(hourly)
        self.assertEqual((w.start_hour, w.end_hour), (11, 12))      # only the sunny break

    def test_weak_sunlight_is_flagged(self):
        w = compute_window([0] * 8 + [40, 60, 80, 90, 80, 60, 40, 20] + [0] * 8)
        self.assertTrue(w.weak)
        self.assertEqual(w.source, 'default')

    def test_wrong_length_or_empty_returns_none(self):
        self.assertIsNone(compute_window([]))
        self.assertIsNone(compute_window([100] * 23))

    def test_none_values_are_treated_as_zero(self):
        hourly = [None] * 8 + [500, 600, 700, 700, 600, 500, 300] + [None] * 9
        w = compute_window(hourly)
        self.assertEqual((w.start_hour, w.end_hour), (8, 14))

    def test_label_is_readable(self):
        self.assertEqual(WINDOW.label, "09:00–16:00")


class GetSolarWindowTests(SimpleTestCase):
    system = SimpleNamespace(has_location=True, latitude=10.0, longitude=76.0)

    def test_network_failure_falls_back_to_default(self):
        with patch('forecast.solar_window.requests.get', side_effect=requests.ConnectionError('offline')), \
                self.assertLogs('forecast.solar_window', level='WARNING'):
            w = get_solar_window(self.system, TOMORROW)
        self.assertEqual(w.source, 'default')
        self.assertEqual((w.start_hour, w.end_hour), (9, 16))

    def test_malformed_response_falls_back(self):
        class R:
            def raise_for_status(self): pass
            def json(self): return {'unexpected': 1}
        with patch('forecast.solar_window.requests.get', return_value=R()), \
                self.assertLogs('forecast.solar_window', level='WARNING'):
            self.assertEqual(get_solar_window(self.system, TOMORROW).source, 'default')

    def test_good_response_uses_hourly_data(self):
        hourly = [0] * 8 + [300, 500, 700, 800, 800, 700, 500, 300] + [0] * 8
        class R:
            def raise_for_status(self): pass
            def json(self): return {'hourly': {'shortwave_radiation': hourly}}
        with patch('forecast.solar_window.requests.get', return_value=R()) as get:
            w = get_solar_window(self.system, TOMORROW)
        self.assertEqual(w.source, 'hourly')
        self.assertEqual(get.call_args.kwargs['params']['start_date'], TOMORROW.isoformat())

    def test_no_location_uses_default_without_calling_api(self):
        with patch('forecast.solar_window.requests.get') as get:
            w = get_solar_window(SimpleNamespace(has_location=False), TOMORROW)
        get.assert_not_called()
        self.assertEqual(w.source, 'default')


# ------------------------------------------------------------ balance (pure)

def sys_(kind):
    return SimpleNamespace(
        needs_battery=kind in ('OFF_GRID', 'HYBRID'), needs_grid_config=kind in ('ON_GRID', 'HYBRID'))


def bat(soc=50, cap=30.0, minimum=20, maximum=100, eff=90):
    b = SimpleNamespace(capacity_kwh=cap, current_soc_percent=soc, minimum_soc_percent=minimum,
                        maximum_soc_percent=maximum, charging_efficiency=eff)
    b.usable_energy_kwh = round(cap * max(0, soc - minimum) / 100, 2)
    return b


def grid(tariff=7.0, export=False, export_tariff=3.0, net=False):
    return SimpleNamespace(import_tariff_per_kwh=tariff, export_enabled=export,
                           export_tariff_per_kwh=export_tariff, net_metering_enabled=net)


class BalanceTests(SimpleTestCase):
    def test_hybrid_deficit_battery_first_then_grid(self):        # your dashboard example
        b = compute_balance(sys_('HYBRID'), 12.81, 27.85, bat(50), grid(7.0))
        self.assertAlmostEqual(b.deficit, 15.04, places=2)
        self.assertAlmostEqual(b.battery_used, 9.0, places=2)
        self.assertAlmostEqual(b.grid_import, 6.04, places=2)
        self.assertAlmostEqual(b.import_cost, 42.28, places=2)
        self.assertAlmostEqual(b.coverage, 0.46, places=2)
        self.assertAlmostEqual(b.co2_avoided_kg, 12.81 * settings.GRID_EMISSION_FACTOR_KG_PER_KWH, places=2)

    def test_on_grid_surplus_exported(self):
        b = compute_balance(sys_('ON_GRID'), 18, 12, None, grid(7, export=True, export_tariff=3))
        self.assertAlmostEqual(b.exported, 6.0)
        self.assertAlmostEqual(b.export_revenue, 18.0)
        self.assertEqual(b.wasted, 0)

    def test_on_grid_surplus_wasted_when_export_off(self):
        b = compute_balance(sys_('ON_GRID'), 18, 12, None, grid(export=False))
        self.assertEqual(b.exported, 0)
        self.assertAlmostEqual(b.wasted, 6.0)

    def test_net_metering_values_export_at_import_tariff(self):
        b = compute_balance(sys_('ON_GRID'), 18, 12, None, grid(7, export=True, export_tariff=3, net=True))
        self.assertAlmostEqual(b.export_revenue, 42.0)

    def test_off_grid_unmet_when_battery_too_small(self):
        b = compute_balance(sys_('OFF_GRID'), 6, 14, bat(50, cap=10), None)
        self.assertAlmostEqual(b.battery_used, 3.0)
        self.assertAlmostEqual(b.unmet, 5.0)
        self.assertEqual(b.grid_import, 0)

    def test_on_grid_ignores_a_battery_it_does_not_use(self):
        b = compute_balance(sys_('ON_GRID'), 5, 10, bat(80), grid())
        self.assertEqual(b.battery_used, 0)
        self.assertAlmostEqual(b.grid_import, 5.0)

    def test_surplus_charges_battery_with_efficiency_loss(self):
        b = compute_balance(sys_('OFF_GRID'), 15, 10, bat(50, cap=10, eff=90), None)
        self.assertAlmostEqual(b.battery_stored, 4.5)               # headroom 5.0, 5 surplus * 0.9
        self.assertAlmostEqual(b.wasted, 0.0)

    def test_full_battery_wastes_surplus(self):
        b = compute_balance(sys_('OFF_GRID'), 15, 10, bat(100, cap=10), None)
        self.assertEqual(b.battery_stored, 0)
        self.assertAlmostEqual(b.wasted, 5.0)

    def test_hybrid_surplus_battery_then_export(self):
        b = compute_balance(sys_('HYBRID'), 30, 10, bat(90, cap=10, eff=100), grid(export=True))
        self.assertAlmostEqual(b.battery_stored, 1.0)
        self.assertAlmostEqual(b.exported, 19.0)

    def test_zero_demand_has_zero_coverage_not_a_crash(self):
        b = compute_balance(sys_('ON_GRID'), 10, 0, None, grid())
        self.assertEqual(b.coverage, 0.0)
        self.assertAlmostEqual(b.surplus, 10)


# ------------------------------------------------------------ engine (database)

def make_user(kind='HYBRID', capacity=3.0, soc=50, battery_cap=30.0, tariff=7.0, export=False, name='asha'):
    user = User.objects.create_user(name, password='pw')
    SolarSystem.objects.create(user=user, system_type=kind, capacity_kw=capacity,
                               latitude=10.0, longitude=76.0, location_name='Test')
    if kind in ('OFF_GRID', 'HYBRID'):
        Battery.objects.create(user=user, capacity_kwh=battery_cap, current_soc_percent=soc,
                               minimum_soc_percent=20, maximum_soc_percent=100, charging_efficiency=90)
    if kind in ('ON_GRID', 'HYBRID'):
        GridConfiguration.objects.create(user=user, import_tariff_per_kwh=tariff,
                                         export_tariff_per_kwh=3.0, export_enabled=export)
    return user


def add_appliance(user, name, watts, hours, priority='MEDIUM', shiftable=False, solar_pref=True,
                  start=None, end=None, active=True):
    return Appliance.objects.create(
        user=user, name=name, category='Test', rated_power_w=watts, average_usage_hours=hours,
        priority=priority, is_shiftable=shiftable, solar_preferred=solar_pref,
        preferred_start_time=start, preferred_end_time=end, is_active=active)


def make_prediction(user, kwh, on=TOMORROW):
    return Prediction.objects.create(
        user=user, prediction_for_date=on, predicted_generation_kwh=kwh,
        capacity_kw_used=user.solarsystem.capacity_kw, model_name='RF')


def types(recs):
    return [r.recommendation_type for r in recs]


class HybridExampleTests(TestCase):
    """The worked example from the planning discussion: 12.81 kWh vs 27.85 kWh, hybrid."""

    def setUp(self):
        self.user = make_user('HYBRID')
        add_appliance(self.user, 'Fridge', 150, 24, 'CRITICAL')            # 3.6
        add_appliance(self.user, 'AC', 1500, 8, 'LOW')                     # 12.0
        add_appliance(self.user, 'Washing Machine', 500, 3, 'MEDIUM', shiftable=True)   # 1.5
        add_appliance(self.user, 'Water Pump', 750, 4, 'HIGH', shiftable=True)          # 3.0
        add_appliance(self.user, 'Geyser', 2000, 3.375, 'MEDIUM')          # 6.75
        add_appliance(self.user, 'TV', 100, 6, 'LOW')                      # 0.6
        add_appliance(self.user, 'Lights', 100, 4, 'HIGH')                 # 0.4
        self.pred = make_prediction(self.user, 12.81)
        self.recs = generate_recommendations(self.user, self.pred, window=WINDOW)

    def test_demand_is_sum_of_active_appliances(self):
        self.assertAlmostEqual(sum(a.daily_energy_kwh for a in Appliance.objects.all()), 27.85, places=2)

    def test_summary_is_first_and_mentions_coverage_cost_and_co2(self):
        first = self.recs[0]
        self.assertEqual(first.recommendation_type, Rec.GENERAL)
        self.assertIn("46%", first.message)
        self.assertIn("6.0 kWh from the grid", first.message)
        self.assertIn("₹42", first.message)
        self.assertIn("CO₂", first.message)
        self.assertIn("estimates", first.message)

    def test_grid_import_and_battery_discharge_present(self):
        self.assertIn(Rec.GRID_IMPORT, types(self.recs))
        self.assertIn(Rec.BATTERY_DISCHARGE, types(self.recs))
        imp = next(r for r in self.recs if r.recommendation_type == Rec.GRID_IMPORT)
        self.assertIn("after your battery's 9.0 kWh is used", imp.message)
        self.assertAlmostEqual(imp.estimated_energy_kwh, 6.04, places=2)

    def test_no_battery_reserve_at_exactly_50_percent(self):             # boundary: rule needs < 50
        self.assertNotIn(Rec.BATTERY_RESERVE, types(self.recs))

    def test_only_shiftable_appliances_get_schedule_tips_largest_first(self):
        sched = [r for r in self.recs if r.recommendation_type == Rec.APPLIANCE_SCHEDULE]
        self.assertEqual([r.appliance.name for r in sched], ['Water Pump', 'Washing Machine'])
        self.assertIn("09:00–16:00", sched[0].message)
        self.assertIn("from the grid", sched[0].message)
        self.assertIsNotNone(sched[0].estimated_savings)

    def test_no_shed_recommendations_when_grid_is_available(self):
        self.assertNotIn(Rec.ENERGY_CONSERVATION, types(self.recs))

    def test_rerun_replaces_instead_of_duplicating(self):
        again = generate_recommendations(self.user, self.pred, window=WINDOW)
        self.assertEqual(Rec.objects.filter(prediction=self.pred).count(), len(again))
        self.assertEqual(len(again), len(self.recs))


class BatteryRuleTests(TestCase):
    def test_battery_reserve_when_poor_day_and_low_battery(self):
        user = make_user('OFF_GRID', soc=45, battery_cap=10)
        add_appliance(user, 'Fan', 1000, 10, 'MEDIUM')                      # 10 kWh
        recs = generate_recommendations(user, make_prediction(user, 3.0), window=WINDOW)
        r = next(r for r in recs if r.recommendation_type == Rec.BATTERY_RESERVE)
        self.assertEqual(r.priority, Rec.HIGH)
        self.assertIn("45%", r.message)

    def test_no_reserve_when_battery_is_healthy(self):
        user = make_user('OFF_GRID', soc=80, battery_cap=10)
        add_appliance(user, 'Fan', 1000, 10)
        recs = generate_recommendations(user, make_prediction(user, 3.0), window=WINDOW)
        self.assertNotIn(Rec.BATTERY_RESERVE, types(recs))

    def test_no_reserve_when_generation_is_good(self):
        user = make_user('OFF_GRID', soc=30, battery_cap=10)
        add_appliance(user, 'Fan', 1000, 10)
        recs = generate_recommendations(user, make_prediction(user, 9.0), window=WINDOW)
        self.assertNotIn(Rec.BATTERY_RESERVE, types(recs))

    def test_surplus_charges_battery_message(self):
        user = make_user('OFF_GRID', soc=50, battery_cap=10)
        add_appliance(user, 'Fan', 500, 10)                                 # 5 kWh
        recs = generate_recommendations(user, make_prediction(user, 8.0), window=WINDOW)
        r = next(r for r in recs if r.recommendation_type == Rec.BATTERY_CHARGE)
        self.assertIn("raising it from 50%", r.message)

    def test_on_grid_gets_no_battery_recommendations(self):
        user = make_user('ON_GRID')
        Battery.objects.create(user=user, capacity_kwh=10, current_soc_percent=10)   # optional extra
        add_appliance(user, 'Fan', 1000, 10)
        recs = generate_recommendations(user, make_prediction(user, 3.0), window=WINDOW)
        self.assertFalse([t for t in types(recs) if t.startswith('BATTERY')])


class OffGridSheddingTests(TestCase):
    """Rainy-day example: 6 kWh predicted, 14 kWh demand, 3 kWh usable battery."""

    def setUp(self):
        self.user = make_user('OFF_GRID', soc=50, battery_cap=10)
        add_appliance(self.user, 'Fridge', 100, 24, 'CRITICAL')              # 2.4
        add_appliance(self.user, 'Lights', 100, 4, 'HIGH')                   # 0.4
        add_appliance(self.user, 'Air Conditioner', 1000, 4, 'LOW')          # 4.0
        add_appliance(self.user, 'Television', 100, 6, 'LOW')                # 0.6
        add_appliance(self.user, 'Washing Machine', 500, 3, 'MEDIUM', shiftable=True)    # 1.5
        add_appliance(self.user, 'Iron Box', 1000, 5.1, 'MEDIUM')            # 5.1
        self.pred = make_prediction(self.user, 6.0)

    def test_defers_low_then_medium_never_high_or_critical(self):
        recs = generate_recommendations(self.user, self.pred, window=WINDOW)
        shed = [r for r in recs if r.recommendation_type == Rec.ENERGY_CONSERVATION]
        names = [r.appliance.name for r in shed if r.appliance]
        self.assertEqual(names[:2], ['Air Conditioner', 'Television'])      # LOW first, largest first
        self.assertNotIn('Fridge', names)
        self.assertNotIn('Lights', names)
        self.assertTrue(all(r.priority == Rec.HIGH for r in shed if r.appliance))

    def test_stops_once_shortfall_is_covered(self):
        # demand 14.0, gen 6.0 -> deficit 8.0, battery 3.0, unmet 5.0
        # AC 4.0 (+TV 0.6 = 4.6, not enough) -> then MEDIUM: shiftable washing machine 1.5 -> 6.1 >= 5
        recs = generate_recommendations(self.user, self.pred, window=WINDOW)
        names = [r.appliance.name for r in recs
                 if r.recommendation_type == Rec.ENERGY_CONSERVATION and r.appliance]
        self.assertEqual(names, ['Air Conditioner', 'Television', 'Washing Machine'])

    def test_an_appliance_is_never_both_postponed_and_scheduled(self):
        recs = generate_recommendations(self.user, self.pred, window=WINDOW)
        postponed = {r.appliance_id for r in recs if r.recommendation_type == Rec.ENERGY_CONSERVATION and r.appliance_id}
        scheduled = {r.appliance_id for r in recs if r.recommendation_type == Rec.APPLIANCE_SCHEDULE}
        self.assertTrue(postponed)
        self.assertFalse(postponed & scheduled)

    def test_summary_mentions_the_uncovered_shortfall(self):
        recs = generate_recommendations(self.user, self.pred, window=WINDOW)
        self.assertIn("cannot be covered", recs[0].message)

    def test_critical_warning_when_even_full_shedding_is_not_enough(self):
        Appliance.objects.filter(name__in=['Air Conditioner', 'Television', 'Washing Machine', 'Iron Box']).update(
            is_active=False)
        add_appliance(self.user, 'Medical Device', 1000, 12, 'CRITICAL')    # essential: 12 kWh
        recs = generate_recommendations(self.user, self.pred, window=WINDOW)
        crit = [r for r in recs if r.priority == Rec.CRITICAL]
        self.assertEqual(len(crit), 1)
        self.assertIn("essential", crit[0].message)
        self.assertIsNone(crit[0].appliance)

    def test_hybrid_never_sheds_because_grid_covers_the_gap(self):
        user = make_user('HYBRID', name='ravi', soc=50, battery_cap=10)
        add_appliance(user, 'Air Conditioner', 1000, 10, 'LOW')
        recs = generate_recommendations(user, make_prediction(user, 2.0), window=WINDOW)
        self.assertNotIn(Rec.ENERGY_CONSERVATION, types(recs))
        self.assertIn(Rec.GRID_IMPORT, types(recs))


class SurplusAndGridTests(TestCase):
    def test_export_recommendation_when_enabled(self):
        user = make_user('ON_GRID', export=True)
        add_appliance(user, 'Fan', 1000, 12)
        recs = generate_recommendations(user, make_prediction(user, 18.0), window=WINDOW)
        r = next(r for r in recs if r.recommendation_type == Rec.GRID_EXPORT)
        self.assertIn("6.0 kWh", r.message)
        self.assertIn("₹18", r.message)
        self.assertEqual(r.estimated_savings, 18.0)

    def test_wasted_surplus_when_export_is_off(self):
        user = make_user('ON_GRID', export=False)
        add_appliance(user, 'Fan', 1000, 12)
        recs = generate_recommendations(user, make_prediction(user, 18.0), window=WINDOW)
        self.assertNotIn(Rec.GRID_EXPORT, types(recs))
        wasted = next(r for r in recs if r.title == "Some surplus solar would be wasted")
        self.assertIn("Export is turned off", wasted.message)

    def test_off_grid_has_no_grid_recommendations(self):
        user = make_user('OFF_GRID')
        add_appliance(user, 'Fan', 1000, 12)
        recs = generate_recommendations(user, make_prediction(user, 3.0), window=WINDOW)
        self.assertFalse([t for t in types(recs) if t.startswith('GRID')])


class ScheduleRuleTests(TestCase):
    def setUp(self):
        self.user = make_user('ON_GRID')

    def _sched(self, **kw):
        add_appliance(self.user, 'Washing Machine', 500, 3, 'MEDIUM', shiftable=True, **kw)
        add_appliance(self.user, 'Fan', 1000, 20, 'MEDIUM')
        recs = generate_recommendations(self.user, make_prediction(self.user, 9.0), window=WINDOW)
        return [r for r in recs if r.recommendation_type == Rec.APPLIANCE_SCHEDULE]

    def test_preferred_time_overlapping_window_is_respected(self):
        sched = self._sched(start=time(11, 0), end=time(14, 0))
        self.assertEqual(len(sched), 1)
        self.assertIn("11:00–14:00", sched[0].message)
        self.assertIn("preferred time", sched[0].message)

    def test_preferred_time_outside_window_explains_the_gap(self):
        sched = self._sched(start=time(19, 0), end=time(21, 0))
        self.assertIn("outside the recommended solar window", sched[0].message)
        self.assertIn("19:00–21:00", sched[0].message)

    def test_not_solar_preferred_is_skipped(self):
        self.assertEqual(self._sched(solar_pref=False), [])

    def test_non_shiftable_is_skipped(self):
        add_appliance(self.user, 'Heater', 1000, 5, 'LOW', shiftable=False)
        recs = generate_recommendations(self.user, make_prediction(self.user, 9.0), window=WINDOW)
        self.assertNotIn(Rec.APPLIANCE_SCHEDULE, types(recs))

    def test_weak_sunlight_skips_shifting_and_says_so(self):
        add_appliance(self.user, 'Washing Machine', 500, 3, 'MEDIUM', shiftable=True)
        weak = default_window(weak=True, peak=90)
        recs = generate_recommendations(self.user, make_prediction(self.user, 9.0), window=weak)
        self.assertNotIn(Rec.APPLIANCE_SCHEDULE, types(recs))
        self.assertTrue(any(r.title == "Very little sunlight expected" for r in recs))

    def test_tiny_generation_skips_shifting(self):
        add_appliance(self.user, 'Washing Machine', 500, 3, 'MEDIUM', shiftable=True)
        recs = generate_recommendations(self.user, make_prediction(self.user, 0.4), window=WINDOW)
        self.assertNotIn(Rec.APPLIANCE_SCHEDULE, types(recs))

    @override_settings(DSS_MAX_SCHEDULE_RECOMMENDATIONS=2)
    def test_caps_number_of_schedule_tips(self):
        for i in range(4):
            add_appliance(self.user, f'Machine {i}', 500, 2 + i, 'MEDIUM', shiftable=True)
        recs = generate_recommendations(self.user, make_prediction(self.user, 9.0), window=WINDOW)
        self.assertEqual(types(recs).count(Rec.APPLIANCE_SCHEDULE), 2)

    def test_default_window_is_labelled_as_such(self):
        add_appliance(self.user, 'Washing Machine', 500, 3, 'MEDIUM', shiftable=True)
        recs = generate_recommendations(self.user, make_prediction(self.user, 9.0), window=default_window())
        msg = next(r for r in recs if r.recommendation_type == Rec.APPLIANCE_SCHEDULE).message
        self.assertIn("hourly sunlight data was unavailable", msg)


class EdgeCaseTests(TestCase):
    def test_no_active_appliances_gives_a_single_advisory(self):
        user = make_user('HYBRID')
        add_appliance(user, 'Old Fan', 100, 2, active=False)
        recs = generate_recommendations(user, make_prediction(user, 10.0), window=WINDOW)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0].recommendation_type, Rec.GENERAL)
        self.assertIn("no active appliances", recs[0].message)

    def test_requires_a_prediction(self):
        user = make_user('ON_GRID')
        with self.assertRaisesMessage(DecisionSupportError, "prediction first"):
            generate_recommendations(user)

    def test_defaults_to_tomorrows_prediction(self):
        user = make_user('ON_GRID')
        add_appliance(user, 'Fan', 1000, 5)
        pred = make_prediction(user, 8.0)
        make_prediction(user, 20.0, on=date.today() + timedelta(days=5))      # a later day must be ignored
        recs = generate_recommendations(user, window=WINDOW)
        self.assertTrue(all(r.prediction_id == pred.id for r in recs))

    def test_requires_a_solar_system(self):
        bare = User.objects.create_user('bare', password='pw')
        with self.assertRaises(DecisionSupportError):
            generate_recommendations(bare)

    def test_other_users_are_not_touched(self):
        a, b = make_user('ON_GRID', name='a'), make_user('ON_GRID', name='b')
        for u in (a, b):
            add_appliance(u, 'Fan', 1000, 5)
        generate_recommendations(a, make_prediction(a, 8.0), window=WINDOW)
        generate_recommendations(b, make_prediction(b, 8.0), window=WINDOW)
        generate_recommendations(a, Prediction.objects.get(user=a), window=WINDOW)
        self.assertTrue(Rec.objects.filter(user=b).exists())
        self.assertFalse(Rec.objects.filter(user=a).exclude(prediction__user=a).exists())

    def test_deleting_an_appliance_keeps_old_advice_with_the_link_cleared(self):
        user = make_user('ON_GRID')
        wm = add_appliance(user, 'Washing Machine', 500, 3, 'MEDIUM', shiftable=True)
        add_appliance(user, 'Fan', 1000, 12)
        past = make_prediction(user, 9.0, on=date.today() - timedelta(days=2))    # history survives staleness
        generate_recommendations(user, past, window=WINDOW)
        self.assertTrue(Rec.objects.filter(appliance=wm).exists())
        wm.delete()
        kept = Rec.objects.filter(prediction=past, message__contains="Washing Machine")
        self.assertTrue(kept.exists())
        self.assertTrue(all(r.appliance_id is None for r in kept))


class StaleRecommendationTests(TestCase):
    def setUp(self):
        self.user = make_user('HYBRID')
        self.fan = add_appliance(self.user, 'Fan', 1000, 12)
        self.pred = make_prediction(self.user, 9.0)
        self.past_pred = make_prediction(self.user, 8.0, on=date.today() - timedelta(days=3))
        generate_recommendations(self.user, self.pred, window=WINDOW)
        generate_recommendations(self.user, self.past_pred, window=WINDOW)
        self.assertTrue(Rec.objects.filter(prediction=self.pred).exists())

    def future(self):
        return Rec.objects.filter(prediction=self.pred).count()

    def past(self):
        return Rec.objects.filter(prediction=self.past_pred).count()

    def test_unrelated_system_edit_keeps_recommendations(self):
        s = self.user.solarsystem
        s.panel_count = 10
        s.save()
        self.assertGreater(self.future(), 0)

    def test_capacity_change_removes_prediction_and_its_recommendations(self):
        s = self.user.solarsystem
        s.capacity_kw = 6.0
        s.save()                                  # forecast signal deletes the prediction -> CASCADE
        self.assertFalse(Prediction.objects.filter(pk=self.pred.pk).exists())
        self.assertEqual(self.future(), 0)
        self.assertGreater(self.past(), 0)

    def test_other_users_recommendations_are_untouched(self):
        other = make_user('ON_GRID', name='other')
        add_appliance(other, 'Fan', 1000, 5)
        generate_recommendations(other, make_prediction(other, 8.0), window=WINDOW)
        add_appliance(self.user, 'Heater', 500, 2)
        self.assertTrue(Rec.objects.filter(user=other).exists())
