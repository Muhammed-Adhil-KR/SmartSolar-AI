from django.urls import path
from . import views

app_name = 'decision_support'

urlpatterns = [
    path('', views.recommendations_tomorrow, name='current'),
    path('history/', views.recommendation_history, name='history'),
    path('refresh/', views.refresh_recommendations, name='refresh'),
]