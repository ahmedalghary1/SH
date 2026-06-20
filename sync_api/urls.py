from django.urls import path
from django.views.decorators.csrf import csrf_exempt

from . import auth, views

urlpatterns = [
    path('sync/ping/', views.ping_view, name='sync_ping'),
    path('auth/login/', csrf_exempt(auth.login_view), name='sync_login'),
    path('auth/refresh/', csrf_exempt(auth.refresh_view), name='sync_refresh'),
    path('auth/me/', auth.me_view, name='sync_me'),
    path('sync/bootstrap/', views.bootstrap_view, name='sync_bootstrap'),
    path('sync/changes/', views.changes_view, name='sync_changes'),
    path('sync/push/', csrf_exempt(views.push_view), name='sync_push'),
]
