from django.urls import path
from . import views

app_name = 'decision_support'

urlpatterns = [
    path('', views.placeholder, name='placeholder'),
]