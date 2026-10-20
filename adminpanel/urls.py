from django.urls import path

from . import views

app_name = 'adminpanel'

urlpatterns = [
    path('', views.overview, name='overview'),

    path('users/', views.user_list, name='users'),
    path('users/<int:pk>/', views.user_detail, name='user_detail'),
    path('users/<int:pk>/toggle/', views.user_toggle_active, name='user_toggle'),
    path('users/<int:pk>/delete/', views.user_delete, name='user_delete'),

    path('systems/', views.system_list, name='systems'),
    path('systems/<int:pk>/', views.system_detail, name='system_detail'),

    path('appliances/', views.appliance_list, name='appliances'),
    path('appliances/<int:pk>/toggle/', views.appliance_toggle, name='appliance_toggle'),
    path('appliances/<int:pk>/delete/', views.appliance_delete, name='appliance_delete'),

    path('predictions/', views.prediction_list, name='predictions'),
    path('predictions/<int:pk>/delete/', views.prediction_delete, name='prediction_delete'),

    path('recommendations/', views.recommendation_list, name='recommendations'),
    path('recommendations/<int:pk>/delete/', views.recommendation_delete, name='recommendation_delete'),
]