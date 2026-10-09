from django.urls import path
from . import views

app_name = 'forecast'

urlpatterns = [
    path('', views.weather_test, name='weather_test'),
]