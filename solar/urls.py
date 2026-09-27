from django.urls import path
from . import views

app_name = 'solar'

urlpatterns = [
    path('setup/location/', views.setup_location, name='setup_location'),
    path('setup/location/confirm/', views.confirm_location, name='confirm_location'),
    path('setup/system/', views.setup_system, name='setup_system'),
    path('setup/battery/', views.setup_battery, name='setup_battery'),
    path('setup/grid/', views.setup_grid, name='setup_grid'),
    path('edit/', views.edit_system, name='edit_system'),
    path('edit/battery/', views.edit_battery, name='edit_battery'),
    path('edit/grid/', views.edit_grid, name='edit_grid'),
    path('appliances/', views.appliance_list, name='appliance_list'),
    path('appliances/add/', views.appliance_add, name='appliance_add'),
    path('appliances/<int:pk>/edit/', views.appliance_edit, name='appliance_edit'),
    path('appliances/<int:pk>/toggle/', views.appliance_toggle_active, name='appliance_toggle_active'),
    path('appliances/<int:pk>/delete/', views.appliance_delete, name='appliance_delete'),
]