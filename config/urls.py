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

admin.site.site_header = "SmartSolar Administration"
admin.site.site_title = "SmartSolar Admin"
admin.site.index_title = "Manage SmartSolar"