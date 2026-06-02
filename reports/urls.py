from django.urls import path

from . import views

app_name = 'reports'

urlpatterns = [
    path('daily-sales/', views.DailySalesReportView.as_view(), name='daily_sales'),
    path('monthly-sales/', views.MonthlySalesReportView.as_view(), name='monthly_sales'),
    path('inventory/', views.InventoryReportView.as_view(), name='inventory'),
    path('customers/', views.CustomerReportView.as_view(), name='customers'),
    path('employees/', views.EmployeeSalesReportView.as_view(), name='employees'),
]
