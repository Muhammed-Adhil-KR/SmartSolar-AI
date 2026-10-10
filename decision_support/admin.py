from django.contrib import admin
from .models import Recommendation


@admin.register(Recommendation)
class RecommendationAdmin(admin.ModelAdmin):
    list_display = ('user', 'prediction', 'recommendation_type', 'priority', 'title', 'created_at')
    list_filter = ('recommendation_type', 'priority')
    search_fields = ('user__username', 'title', 'message')
