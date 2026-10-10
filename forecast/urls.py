from django.urls import path
from . import views

app_name = 'forecast'

urlpatterns = [
    path('generate/', views.generate_prediction, name='generate_prediction'),
    path('history/', views.prediction_history, name='prediction_history'),
]