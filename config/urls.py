from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls', namespace='accounts')),
    path('solar/', include('solar.urls', namespace='solar')),
    path('forecast/', include('forecast.urls', namespace='forecast')),
    path('recommendations/', include('decision_support.urls', namespace='decision_support')),
    path('', include('dashboard.urls', namespace='dashboard')),
]