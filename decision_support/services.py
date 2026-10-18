"""
Decision Support Engine.

Prediction (ML) and decision-making (DSS) are separate: this module never
calls the model. It reads the saved Prediction plus the user's own data and
turns them into Recommendation rows.

HOW IT WORKS
  1. compute_balance()  - tomorrow's energy balance: generation vs. expected
                          usage, and where any surplus/deficit goes.
  2. Rule groups        - appliance, battery and grid methods each apply a
                          small set of documented rules to that balance.
  3. run()              - replaces the day's recommendations with the new set.

SIMPLIFICATION (state this in the report): the balance works on DAILY totals
and assumes generation and usage can be matched in time. Shifting flexible
loads into the solar window is what makes that assumption closer to true.
Every figure is an estimate.

RULES (each is marked R# in the code below)
  Appliance (all system types)
    R1  Shift flexible, solar-preferred appliances into the solar window.
    R6  OFF_GRID only: if the battery cannot cover the shortfall, defer
        LOW then MEDIUM priority appliances (never HIGH / CRITICAL).
  Battery (OFF_GRID / HYBRID only)
    R3  Surplus solar will charge the battery.
    R7  Poor-generation day AND low battery -> protect the battery.
    R10 Battery will supply part of the deficit -> use it after the sun is gone.
  Grid (ON_GRID / HYBRID only)
    R2  Surplus can be exported (if export is enabled).
    R5  Expected grid import and its cost.
  General
    R4  Surplus that nothing can absorb would be wasted.
    R8  Daily summary: coverage, savings, CO2 avoided.
    R9  No active appliances -> advisory only.
"""
import logging
from dataclasses import dataclass
from datetime import date, timedelta

from django.conf import settings
from django.db import transaction

from forecast.models import Prediction
from forecast.solar_window import get_solar_window
from solar.models import Appliance, Battery, GridConfiguration
from .models import Recommendation as Rec

logger = logging.getLogger(__name__)


class DecisionSupportError(Exception):
    """Raised when recommendations cannot be generated (missing prediction/system)."""


# ---------------------------------------------------------------- balance

@dataclass
class EnergyBalance:
    generation: float
    demand: float
    coverage: float            # generation / demand (0 if no demand)
    surplus: float
    deficit: float
    self_consumed: float       # solar energy used directly: min(generation, demand)
    battery_used: float        # deficit covered by the battery
    grid_import: float         # deficit covered by the grid
    unmet: float               # deficit nothing can cover (off-grid)
    battery_stored: float      # surplus stored in the battery (after charging losses)
    exported: float            # surplus sent to the grid
    wasted: float              # surplus nothing can absorb
    import_cost: float
    export_revenue: float
    co2_avoided_kg: float


def compute_balance(system, generation, demand, battery=None, grid=None):
    """
    Pure calculation. Battery rules apply only if the system type uses a battery,
    grid rules only if it uses the grid (consistent with the Phase 3 gating).
    """
    battery = battery if system.needs_battery else None
    grid = grid if system.needs_grid_config else None

    surplus = max(generation - demand, 0.0)
    deficit = max(demand - generation, 0.0)

    # --- deficit: battery first, then grid; off-grid has nothing after the battery
    usable = battery.usable_energy_kwh if battery else 0.0
    battery_used = min(deficit, usable)
    remaining = deficit - battery_used
    grid_import = remaining if grid else 0.0
    unmet = 0.0 if grid else remaining

    # --- surplus: battery first (limited by headroom and charging losses), then export
    stored = 0.0
    left = surplus
    if battery and surplus > 0:
        eff = battery.charging_efficiency / 100.0
        headroom = battery.capacity_kwh * max(battery.maximum_soc_percent - battery.current_soc_percent, 0) / 100.0
        absorbed = min(surplus, headroom / eff if eff > 0 else 0.0)     # solar energy sent to the battery
        stored = absorbed * eff
        left = surplus - absorbed
    exported = left if (grid and grid.export_enabled) else 0.0
    wasted = left - exported

    import_cost = grid_import * grid.import_tariff_per_kwh if grid else 0.0
    if grid and exported > 0:
        rate = grid.import_tariff_per_kwh if grid.net_metering_enabled else (grid.export_tariff_per_kwh or 0.0)
        export_revenue = exported * rate
    else:
        export_revenue = 0.0

    self_consumed = min(generation, demand)
    return EnergyBalance(
        generation=generation, demand=demand,
        coverage=(generation / demand) if demand > 0 else 0.0,
        surplus=surplus, deficit=deficit, self_consumed=self_consumed,
        battery_used=battery_used, grid_import=grid_import, unmet=unmet,
        battery_stored=stored, exported=exported, wasted=wasted,
        import_cost=import_cost, export_revenue=export_revenue,
        co2_avoided_kg=self_consumed * settings.GRID_EMISSION_FACTOR_KG_PER_KWH,
    )


# ---------------------------------------------------------------- formatting

def _kwh(x):
    return f"{x:.1f}"


def _money(x):
    symbol = settings.CURRENCY_SYMBOL
    return f"{symbol}{x:,.0f}" if x >= 10 else f"{symbol}{x:.1f}"


def _hhmm(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _minutes(t):
    return t.hour * 60 + t.minute


PRIORITY_RANK = {Appliance.LOW: 0, Appliance.MEDIUM: 1, Appliance.HIGH: 2, Appliance.CRITICAL: 3}


# ---------------------------------------------------------------- engine

class DecisionSupportEngine:
    def __init__(self, user, prediction, solar_system, appliances, battery=None,
                 grid_config=None, window=None):
        self.user = user
        self.prediction = prediction
        self.system = solar_system
        self.appliances = [a for a in appliances if a.is_active]
        self.battery = battery
        self.grid = grid_config
        self.window = window
        self.demand = round(sum(a.daily_energy_kwh for a in self.appliances), 3)
        self.balance = compute_balance(
            solar_system, prediction.predicted_generation_kwh, self.demand, battery, grid_config)
        # gated views of the optional parts
        self._battery = battery if solar_system.needs_battery else None
        self._grid = grid_config if solar_system.needs_grid_config else None

    # -- helper ------------------------------------------------------
    def _rec(self, rtype, priority, title, message, appliance=None, energy=None, savings=None):
        return Rec(user=self.user, prediction=self.prediction, appliance=appliance,
                   recommendation_type=rtype, priority=priority, title=title, message=message,
                   estimated_energy_kwh=None if energy is None else round(energy, 2),
                   estimated_savings=None if savings is None else round(savings, 2))

    # -- cost and carbon (spec categories) ---------------------------
    def estimate_cost_savings(self):
        """Money saved by using your own solar, plus any export income. Estimates."""
        b = self.balance
        if not self._grid:
            return {'applicable': False, 'self_use_savings': 0.0, 'export_revenue': 0.0,
                    'total_savings': 0.0, 'import_cost': 0.0}
        self_use = b.self_consumed * self._grid.import_tariff_per_kwh
        return {'applicable': True, 'self_use_savings': self_use, 'export_revenue': b.export_revenue,
                'total_savings': self_use + b.export_revenue, 'import_cost': b.import_cost}

    def estimate_carbon_reduction(self):
        b = self.balance
        return {'co2_avoided_kg': b.co2_avoided_kg, 'self_consumed_kwh': b.self_consumed,
                'factor': settings.GRID_EMISSION_FACTOR_KG_PER_KWH}

    # -- appliance rules ---------------------------------------------
    def generate_appliance_recommendations(self):
        recs, b, w = [], self.balance, self.window
        if not self.appliances:
            return recs

        # R6 first, so an appliance we tell the user to postpone is never also told to "run now"
        shed = self._shed_recs() if b.unmet > 0.05 else []
        postponed = {r.appliance_id for r in shed if r.appliance_id}

        # R1: shift flexible appliances into the solar window
        if w is not None and w.weak:
            recs.append(self._rec(
                Rec.GENERAL, Rec.MEDIUM, "Very little sunlight expected",
                f"Tomorrow's sunlight is expected to be weak (peak about {w.peak_wm2:.0f} W/m²), "
                f"so moving appliances into the daytime will not help much."))
        elif w is not None and self.prediction.predicted_generation_kwh >= settings.DSS_MIN_USEFUL_GENERATION_KWH:
            candidates = sorted(
                (a for a in self.appliances
                 if a.is_shiftable and a.solar_preferred and a.id not in postponed),
                key=lambda a: -a.daily_energy_kwh)[:settings.DSS_MAX_SCHEDULE_RECOMMENDATIONS]
            win_s, win_e = w.start_hour * 60, w.end_hour * 60
            for a in candidates:
                recs.append(self._schedule_rec(a, win_s, win_e))

        recs.extend(shed)
        return recs

    def _schedule_rec(self, a, win_s, win_e):
        b, w = self.balance, self.window
        energy = a.daily_energy_kwh
        in_deficit = b.deficit > 0.05
        if self._grid and b.grid_import > 0:
            savings = min(energy, b.grid_import) * self._grid.import_tariff_per_kwh
            benefit = "to use solar power directly instead of buying it from the grid"
        elif in_deficit:
            savings = None
            benefit = "to use solar power directly and reduce the drain on your battery"
        else:
            savings = None
            benefit = "to make the most of free solar power"
        priority = Rec.MEDIUM if in_deficit else Rec.LOW

        ps, pe = a.preferred_start_time, a.preferred_end_time
        has_pref = ps is not None and pe is not None and _minutes(ps) < _minutes(pe)
        if has_pref:
            lo, hi = max(_minutes(ps), win_s), min(_minutes(pe), win_e)
            if hi > lo:
                when = f"{_hhmm(lo)}–{_hhmm(hi)}"
                msg = (f"Run {a.name} ({_kwh(energy)} kWh) between {when}, inside your preferred time and "
                       f"the recommended solar window {w.label} ({w.source_note}) {benefit}.")
            else:
                msg = (f"Your preferred time for {a.name} ({_hhmm(_minutes(ps))}–{_hhmm(_minutes(pe))}) "
                       f"is outside the recommended solar window {w.label} ({w.source_note}). "
                       f"Running its {_kwh(energy)} kWh inside the window would help {benefit[3:]}.")
        else:
            msg = (f"Run {a.name} ({_kwh(energy)} kWh) between {w.label} {benefit}. "
                   f"This is the recommended solar window ({w.source_note}).")
        return self._rec(Rec.APPLIANCE_SCHEDULE, priority, f"Run {a.name} during sunny hours",
                         msg, appliance=a, energy=energy, savings=savings)

    def _shed_recs(self):
        """R6: defer LOW then MEDIUM priority appliances until the shortfall is covered."""
        b = self.balance
        candidates = sorted(
            (a for a in self.appliances if a.priority in (Appliance.LOW, Appliance.MEDIUM)),
            key=lambda a: (PRIORITY_RANK[a.priority], not a.is_shiftable, -a.daily_energy_kwh))
        recs, needed = [], b.unmet
        for a in candidates:
            if needed <= 0.05:
                break
            recs.append(self._rec(
                Rec.ENERGY_CONSERVATION, Rec.HIGH, f"Postpone {a.name}",
                f"Postpone {a.name} ({a.get_priority_display().upper()} priority, "
                f"{_kwh(a.daily_energy_kwh)} kWh) to avoid draining your battery"
                f"{' and run it on a sunnier day' if a.priority == Appliance.MEDIUM else ''}.",
                appliance=a, energy=a.daily_energy_kwh))
            needed -= a.daily_energy_kwh
        if needed > 0.05:
            recs.append(self._rec(
                Rec.ENERGY_CONSERVATION, Rec.CRITICAL, "Battery cannot cover essential loads",
                f"Even after postponing all low and medium priority appliances, about {_kwh(needed)} kWh "
                f"of your essential (high and critical priority) usage may not be covered tomorrow. "
                f"Reduce essential usage where possible."))
        return recs

    # -- battery rules (OFF_GRID / HYBRID) ----------------------------
    def generate_battery_recommendations(self):
        recs = []
        bat, b, w = self._battery, self.balance, self.window
        if not bat or not self.appliances:
            return recs

        # R7: poor-generation day and low battery
        if b.coverage < settings.DSS_LOW_COVERAGE_RATIO and bat.current_soc_percent < settings.DSS_LOW_BATTERY_SOC_PERCENT:
            recs.append(self._rec(
                Rec.BATTERY_RESERVE, Rec.HIGH, "Protect your battery tomorrow",
                f"Tomorrow's generation is low (about {b.coverage * 100:.0f}% of your expected usage) "
                f"and your battery is at {bat.current_soc_percent:.0f}%. Avoid running heavy loads from the "
                f"battery and try to keep it above its minimum of {bat.minimum_soc_percent:.0f}%."))

        # R10: battery supplies part of the deficit
        if b.battery_used > 0.05:
            after = f" after about {w.end_hour:02d}:00 when the sun fades" if w is not None else " after sunset"
            recs.append(self._rec(
                Rec.BATTERY_DISCHARGE, Rec.MEDIUM, "Use your battery in the evening",
                f"Your battery is expected to supply about {_kwh(b.battery_used)} kWh tomorrow. "
                f"Plan your heavier loads for the evening,{after}.",
                energy=b.battery_used))

        # R3: surplus charges the battery
        if b.battery_stored > 0.05:
            new_soc = min(bat.current_soc_percent + b.battery_stored / bat.capacity_kwh * 100,
                          bat.maximum_soc_percent)
            recs.append(self._rec(
                Rec.BATTERY_CHARGE, Rec.LOW, "Surplus solar will charge your battery",
                f"About {_kwh(b.battery_stored)} kWh of surplus solar can be stored in your battery, "
                f"raising it from {bat.current_soc_percent:.0f}% to about {new_soc:.0f}%.",
                energy=b.battery_stored))
        return recs

    # -- grid rules (ON_GRID / HYBRID) --------------------------------
    def generate_grid_recommendations(self):
        recs, g, b = [], self._grid, self.balance
        if not g or not self.appliances:
            return recs

        # R5: expected import
        if b.grid_import > 0.05:
            after = (f" after your battery's {_kwh(b.battery_used)} kWh is used"
                     if b.battery_used > 0.05 else "")
            recs.append(self._rec(
                Rec.GRID_IMPORT, Rec.HIGH if b.coverage < settings.DSS_LOW_COVERAGE_RATIO else Rec.MEDIUM,
                "Expect to import from the grid",
                f"Expect to draw about {_kwh(b.grid_import)} kWh from the grid{after}, "
                f"costing about {_money(b.import_cost)}.",
                energy=b.grid_import))

        # R2: export surplus
        if b.exported > 0.05:
            recs.append(self._rec(
                Rec.GRID_EXPORT, Rec.LOW, "Surplus can be exported",
                f"About {_kwh(b.exported)} kWh of surplus can be exported to the grid, "
                f"worth about {_money(b.export_revenue)}.",
                energy=b.exported, savings=b.export_revenue))
        return recs

    # -- general rules ------------------------------------------------
    def generate_general_recommendations(self):
        recs, b = [], self.balance
        if not self.appliances:
            # R9
            return [self._rec(
                Rec.GENERAL, Rec.MEDIUM, "Add your appliances for personalised advice",
                f"You have no active appliances, so recommendations cannot be personalised. "
                f"Tomorrow's predicted generation is {_kwh(b.generation)} kWh. "
                f"Add or activate your appliances to get scheduling advice.")]

        # R8: summary (placed first)
        parts = [f"Tomorrow your solar system is expected to cover about {b.coverage * 100:.0f}% of your "
                 f"expected usage ({_kwh(b.generation)} of {_kwh(b.demand)} kWh)."]
        if b.surplus > 0.05:
            parts.append(f"You will have about {_kwh(b.surplus)} kWh spare.")
        if self._grid:
            parts.append(f"You are likely to import about {_kwh(b.grid_import)} kWh from the grid"
                         f"{', costing about ' + _money(b.import_cost) if b.grid_import > 0.05 else ''}."
                         if b.grid_import > 0.05 else "No grid import is expected.")
        if self._battery and b.battery_used > 0.05:
            parts.append(f"Your battery is expected to supply about {_kwh(b.battery_used)} kWh.")
        if b.unmet > 0.05:
            parts.append(f"About {_kwh(b.unmet)} kWh of the shortfall cannot be covered.")
        parts.append(f"Self-consumed solar avoids about {b.co2_avoided_kg:.1f} kg CO₂.")
        parts.append("All figures are estimates.")
        cost = self.estimate_cost_savings()
        recs.append(self._rec(
            Rec.GENERAL, Rec.LOW, Rec.SUMMARY_TITLE, " ".join(parts),
            energy=b.self_consumed, savings=cost['total_savings'] if cost['applicable'] else None))

        # R4: surplus that nothing can absorb
        if b.wasted > 0.05:
            if self._grid and not self._grid.export_enabled:
                tip = "Export is turned off in your grid settings, and your battery cannot take more."
            else:
                tip = "Nothing can absorb it."
            recs.append(self._rec(
                Rec.GENERAL, Rec.LOW, "Some surplus solar would be wasted",
                f"About {_kwh(b.wasted)} kWh of surplus solar would be wasted. {tip} "
                f"Consider running extra loads during the day.",
                energy=b.wasted))
        return recs

    # -- orchestration ------------------------------------------------
    def build(self):
        if not self.appliances:
            return self.generate_general_recommendations()           # R9 only
        general = self.generate_general_recommendations()
        summary, extras = general[:1], general[1:]
        return (summary + self.generate_grid_recommendations() + self.generate_battery_recommendations()
                + self.generate_appliance_recommendations() + extras)

    @transaction.atomic
    def run(self):
        """Replace this prediction's recommendations with a fresh set and save them."""
        recs = self.build()
        Rec.objects.filter(prediction=self.prediction).delete()
        Rec.objects.bulk_create(recs)
        return list(Rec.objects.filter(prediction=self.prediction).order_by('id'))


def _load_engine(user, prediction, window=None):
    """Load the user's current data and return a ready DecisionSupportEngine."""
    system = getattr(user, 'solarsystem', None)
    if system is None:
        raise DecisionSupportError("Set up your solar system before generating recommendations.")
    return DecisionSupportEngine(
        user, prediction, system,
        list(Appliance.objects.filter(user=user, is_active=True)),
        battery=Battery.objects.filter(user=user).first(),
        grid_config=GridConfiguration.objects.filter(user=user).first(),
        window=window)


def tomorrows_prediction(user):
    return Prediction.objects.filter(
        user=user, prediction_for_date=date.today() + timedelta(days=1)).first()


def generate_recommendations(user, prediction=None, window=None):
    """
    Run the engine for one prediction (default: tomorrow's) and save the result.
    Raises DecisionSupportError if it can't run.
    """
    if getattr(user, 'solarsystem', None) is None:
        raise DecisionSupportError("Set up your solar system before generating recommendations.")
    if prediction is None:
        prediction = tomorrows_prediction(user)
    if prediction is None:
        raise DecisionSupportError("Generate tomorrow's prediction first; recommendations are built from it.")
    if window is None:
        window = get_solar_window(user.solarsystem, prediction.prediction_for_date)
    return _load_engine(user, prediction, window).run()


def refresh_open_recommendations(user, window=None):
    """
    Rebuild the advice for every OPEN day (a prediction dated today or later) so it
    matches the user's current appliances, battery, grid and system type. Past days
    are never touched, so they stay as history.

    Called by the settings views right after a successful save. It never raises
    (a failure here must not undo or block the user's save). Returns how many
    recommendations were written; 0 if there was nothing to rebuild.
    """
    try:
        if getattr(user, 'solarsystem', None) is None:
            return 0
        open_predictions = Prediction.objects.filter(
            user=user, prediction_for_date__gte=date.today()).order_by('prediction_for_date')
        total = 0
        for prediction in open_predictions:
            total += len(generate_recommendations(user, prediction, window=window))
        return total
    except Exception:
        logger.exception("Could not refresh recommendations for user %s", getattr(user, 'pk', None))
        return 0


# ---------------------------------------------------------------- reading helpers for the UI

def summary_tiles(user, prediction):
    """
    The four headline numbers shown above the recommendation cards. Calculated from
    the same balance the engine uses; nothing extra is stored. Tiles that don't apply
    to the user's system type (grid / battery) are left out. Empty if no active appliances.
    """
    engine = _load_engine(user, prediction)
    if not engine.appliances:
        return []
    b, system = engine.balance, engine.system
    tiles = [{'icon': 'bi-sun', 'label': 'Usage covered by solar', 'value': f"{b.coverage * 100:.0f}%"}]
    if system.needs_grid_config:
        tiles.append({'icon': 'bi-plug', 'label': 'Expected grid import', 'value': f"{b.grid_import:.1f} kWh"})
    if system.needs_battery:
        tiles.append({'icon': 'bi-battery-half', 'label': 'Battery supply', 'value': f"{b.battery_used:.1f} kWh"})
    tiles.append({'icon': 'bi-tree', 'label': 'CO\u2082 avoided', 'value': f"{b.co2_avoided_kg:.1f} kg"})
    return tiles


def dashboard_recommendations(prediction, limit=3):
    """(most important actionable recommendations, total count) for the dashboard card. Summary excluded."""
    if prediction is None:
        return [], 0
    qs = Rec.objects.filter(prediction=prediction)
    top = list(qs.exclude(title=Rec.SUMMARY_TITLE).by_priority()[:limit])
    return top, qs.count()

def energy_split(user, prediction):
    """
    Data for the dashboard "how much of tomorrow's usage does the sun cover?" bar.
    Returns None when it can't be shown (no prediction, or no active appliances).

    solar_pct   share of expected usage covered by solar, capped at 100 for the bar
    other_pct   the rest of the bar (what must come from battery and/or grid)
    other_label "Battery", "Grid" or "Battery + grid", depending on the system type
    spare_kwh   solar left over when generation exceeds usage (0 otherwise)
    unmet_kwh   usage that nothing can cover (off-grid only)
    """
    if prediction is None:
        return None
    engine = _load_engine(user, prediction)
    if not engine.appliances or engine.balance.demand <= 0:
        return None
    b, system = engine.balance, engine.system

    solar_pct = min(b.coverage, 1.0) * 100
    if system.needs_battery and system.needs_grid_config:
        label = 'Battery + grid'
    elif system.needs_battery:
        label = 'Battery'
    else:
        label = 'Grid'
    return {
        'solar_pct': round(solar_pct),
        'other_pct': 100 - round(solar_pct),
        'other_label': label,
        'coverage_pct': round(b.coverage * 100),
        'demand_kwh': round(b.demand, 1),
        'solar_kwh': round(min(b.generation, b.demand), 1),
        'spare_kwh': round(b.surplus, 1),
        'unmet_kwh': round(b.unmet, 1),
    }