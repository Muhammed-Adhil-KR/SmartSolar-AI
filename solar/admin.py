from django.contrib import admin
from .models import SolarSystem, Battery, GridConfiguration


@admin.register(SolarSystem)
class SolarSystemAdmin(admin.ModelAdmin):
    list_display = ('user', 'system_type', 'capacity_kw', 'installation_date', 'updated_at')
    list_filter = ('system_type',)
    search_fields = ('user__username',)


@admin.register(Battery)
class BatteryAdmin(admin.ModelAdmin):
    list_display = ('user', 'capacity_kwh', 'current_soc_percent', 'updated_at')
    search_fields = ('user__username',)


@admin.register(GridConfiguration)
class GridConfigurationAdmin(admin.ModelAdmin):
    list_display = ('user', 'import_tariff_per_kwh', 'export_enabled', 'net_metering_enabled')
    search_fields = ('user__username',)