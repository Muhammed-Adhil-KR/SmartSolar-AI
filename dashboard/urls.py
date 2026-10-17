from django.urls import path

from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.landing, name='landing'),          # public Home page  -> /
    path('dashboard/', views.home, name='home'),      # the dashboard     -> /dashboard/
]