from django import forms
from .models import SolarSystem, Battery, GridConfiguration, Appliance


class LocationSearchForm(forms.Form):
    query = forms.CharField(
        label="Enter your detailed location",
        max_length=255,
        widget=forms.TextInput(attrs={
            'placeholder': 'e.g. Amboori, Thiruvananthapuram, Kerala (be as specific as possible)'
        })
    )


class SolarSystemForm(forms.ModelForm):
    class Meta:
        model = SolarSystem
        fields = ['system_type', 'capacity_kw', 'panel_count', 'inverter_capacity_kw', 'installation_date']
        widgets = {
            'installation_date': forms.DateInput(attrs={'type': 'date'}),
        }


class BatteryForm(forms.ModelForm):
    class Meta:
        model = Battery
        fields = [
            'capacity_kwh', 'current_soc_percent', 'minimum_soc_percent',
            'maximum_soc_percent', 'charging_efficiency',
            'maximum_charge_rate_kw', 'maximum_discharge_rate_kw',
        ]


class GridConfigurationForm(forms.ModelForm):
    class Meta:
        model = GridConfiguration
        fields = ['import_tariff_per_kwh', 'export_tariff_per_kwh', 'export_enabled', 'net_metering_enabled']

class ApplianceForm(forms.ModelForm):
    class Meta:
        model = Appliance
        fields = [
            'name', 'category', 'rated_power_w', 'average_usage_hours',
            'priority', 'is_shiftable', 'solar_preferred',
            'preferred_start_time', 'preferred_end_time',
        ]
        widgets = {
            'preferred_start_time': forms.TimeInput(attrs={'type': 'time'}),
            'preferred_end_time': forms.TimeInput(attrs={'type': 'time'}),
        }