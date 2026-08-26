from django.contrib import admin
from .models import Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'phone', 'location_name', 'latitude', 'longitude', 'updated_at')
    search_fields = ('user__username', 'user__email', 'location_name')