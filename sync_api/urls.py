from django.urls import path
from django.views.decorators.csrf import csrf_exempt

from . import auth, openapi, views

urlpatterns = [
    path('schema/', openapi.openapi_schema, name='api_schema'),
    path('docs/', openapi.swagger_ui, name='api_docs'),
    path('sync/ping/', views.ping_view, name='sync_ping'),
    path('auth/login/', csrf_exempt(auth.login_view), name='sync_login'),
    path('auth/refresh/', csrf_exempt(auth.refresh_view), name='sync_refresh'),
    path('auth/me/', auth.me_view, name='sync_me'),
    path('sync/bootstrap/', views.bootstrap_view, name='sync_bootstrap'),
    path('sync/changes/', views.changes_view, name='sync_changes'),
    path('sync/push/', csrf_exempt(views.push_view), name='sync_push'),
    path('sync/bootstrap-browser/', views.browser_bootstrap_view, name='sync_browser_bootstrap'),
    path('sync/changes-browser/', views.browser_changes_view, name='sync_browser_changes'),
    path('sync/sales/', views.browser_sync_sales_view, name='sync_browser_sales'),
    path('sync/products/', views.browser_sync_products_view, name='sync_browser_products'),
    path('sync/stock/', views.browser_sync_stock_view, name='sync_browser_stock'),
    path('sync/customers/', views.browser_sync_customers_view, name='sync_browser_customers'),
    path('sync/cash/', views.browser_sync_cash_view, name='sync_browser_cash'),
    path('sync/returns/', views.browser_sync_returns_view, name='sync_browser_returns'),
    path('sync/driver-actions/', views.browser_sync_driver_actions_view, name='sync_browser_driver_actions'),
]
