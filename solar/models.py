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

    # Location fields, moved here from the removed Profile model.
    location_name = models.CharField(max_length=255, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

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

    @property
    def has_location(self):
        return self.latitude is not None and self.longitude is not None


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

class Appliance(models.Model):
    CRITICAL = 'CRITICAL'
    HIGH = 'HIGH'
    MEDIUM = 'MEDIUM'
    LOW = 'LOW'
    PRIORITY_CHOICES = [
        (CRITICAL, 'Critical'),
        (HIGH, 'High'),
        (MEDIUM, 'Medium'),
        (LOW, 'Low'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='appliances')

    name = models.CharField(
        max_length=100,
        help_text="Your own label for this appliance, e.g. 'Kitchen Fridge', 'Bedroom AC 1'."
    )
    category = models.CharField(
        max_length=100,
        help_text="Functional group, e.g. 'Refrigeration', 'Cooling', 'Laundry'. Used to group appliances, not to identify a single one."
    )
    rated_power_w = models.FloatField(
        validators=[MinValueValidator(1)],
        help_text="Power rating in Watts, usually printed on the appliance nameplate."
    )
    average_usage_hours = models.FloatField(
        validators=[MinValueValidator(0), MaxValueValidator(24)],
        help_text="Typical hours per day this appliance runs."
    )
    daily_energy_kwh = models.FloatField(
        editable=False, default=0,
        help_text="Auto-calculated: rated power (W) x usage hours / 1000."
    )

    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default=MEDIUM)
    is_shiftable = models.BooleanField(
        default=False,
        help_text="Can this appliance's usage time be moved to align with solar availability?"
    )
    solar_preferred = models.BooleanField(
        default=True,
        help_text="Should the system try to schedule this appliance during solar generation hours?"
    )
    preferred_start_time = models.TimeField(
        null=True, blank=True,
        help_text="Optional: earliest time you'd normally like this appliance running."
    )
    preferred_end_time = models.TimeField(
        null=True, blank=True,
        help_text="Optional: latest time you'd normally like this appliance running."
    )
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-priority', 'name']

    def save(self, *args, **kwargs):
        # Always recompute from source fields so this can never drift out of sync.
        self.daily_energy_kwh = round((self.rated_power_w * self.average_usage_hours) / 1000, 3)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.user.username})"


class SolarGeneration(models.Model):
    MANUAL = 'MANUAL'
    CSV = 'CSV'
    INVERTER = 'INVERTER'
    SOURCE_CHOICES = [
        (MANUAL, 'Manual Entry'),
        (CSV, 'CSV Upload'),
        (INVERTER, 'Inverter (future)'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='generations')
    date = models.DateField()
    generation_kwh = models.FloatField(validators=[MinValueValidator(0)])
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default=MANUAL)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'date')
        ordering = ['-date']

    def __str__(self):
        return f"{self.user.username} - {self.date} - {self.generation_kwh} kWh"