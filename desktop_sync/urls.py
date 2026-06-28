from django.urls import path

from . import views


app_name = 'desktop_sync'

urlpatterns = [
    path('', views.status_view, name='status'),
    path('login/', views.login_view, name='login'),
    path('pull/', views.pull_view, name='pull'),
    path('push/', views.push_view, name='push'),
    path('sync/', views.sync_view, name='sync'),
]
