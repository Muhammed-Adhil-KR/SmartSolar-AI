from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator


class SolarSystem(models.Model):
    ON_GRID = 'ON_GRID'
    OFF_GRID = 'OFF_GRID'
    HYBRID = 'HYBRID'
    SYSTEM_TYPE_CHOICES = [
        (ON_GRID, 'On-Grid'),
        (OFF_GRID, 'Off-Grid'),
        (HYBRID, 'Hybrid'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='solarsystem')
    system_type = models.CharField(max_length=10, choices=SYSTEM_TYPE_CHOICES)
    capacity_kw = models.FloatField(
        validators=[MinValueValidator(0.1), MaxValueValidator(1000)],
        help_text="Installed solar panel capacity in kW."
    )
    panel_count = models.PositiveIntegerField(null=True, blank=True)
    inverter_capacity_kw = models.FloatField(null=True, blank=True)
    installation_date = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username}'s {self.get_system_type_display()} system ({self.capacity_kw} kW)"

    @property
    def needs_battery(self):
        return self.system_type in (self.OFF_GRID, self.HYBRID)

    @property
    def needs_grid_config(self):
        return self.system_type in (self.ON_GRID, self.HYBRID)


class Battery(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='battery')
    capacity_kwh = models.FloatField(
        validators=[MinValueValidator(0.1)],
        help_text="Total usable storage capacity of your battery, in kWh (e.g. a 5 kWh battery)."
    )
    current_soc_percent = models.FloatField(
        default=50, validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Current State of Charge — how full the battery is right now (%). Update this manually whenever you check it."
    )
    minimum_soc_percent = models.FloatField(
        default=20, validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Lowest charge level the battery should be allowed to drop to, to protect battery health (commonly 20%)."
    )
    maximum_soc_percent = models.FloatField(
        default=100, validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Highest charge level the battery should be charged to (often 100%, sometimes capped lower for longevity)."
    )
    charging_efficiency = models.FloatField(
        default=90, validators=[MinValueValidator(1), MaxValueValidator(100)],
        help_text="Percentage of energy actually stored vs. energy put in — accounts for losses as heat while charging."
    )
    maximum_charge_rate_kw = models.FloatField(
        null=True, blank=True,
        help_text="Optional: fastest rate (kW) your battery can be charged at. Leave blank if unknown."
    )
    maximum_discharge_rate_kw = models.FloatField(
        null=True, blank=True,
        help_text="Optional: fastest rate (kW) your battery can be discharged at. Leave blank if unknown."
    )

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username}'s battery ({self.capacity_kwh} kWh)"


class GridConfiguration(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='gridconfiguration')
    import_tariff_per_kwh = models.FloatField(
        validators=[MinValueValidator(0)],
        help_text="What your electricity provider charges per kWh drawn from the grid (used to estimate savings)."
    )
    export_tariff_per_kwh = models.FloatField(
        validators=[MinValueValidator(0)], null=True, blank=True,
        help_text="What you're paid/credited per kWh of surplus solar exported to the grid. Leave blank if not paid separately."
    )
    export_enabled = models.BooleanField(
        default=False,
        help_text="Does your connection allow exporting surplus solar power back to the grid?"
    )
    net_metering_enabled = models.BooleanField(
        default=False,
        help_text="Does your utility offset your bill using exported units (net metering) instead of a separate cash payment?"
    )

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username}'s grid config"