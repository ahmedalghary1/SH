from django.urls import path

from . import views

app_name = 'sales_reps'

urlpatterns = [
    path('', views.SalesRepDashboardView.as_view(), name='dashboard'),
    path('assignments/', views.AssignmentListView.as_view(), name='assignments'),
    path('assign/', views.AssignStockView.as_view(), name='assign_stock'),
    path('return-stock/', views.ReturnStockView.as_view(), name='return_stock'),
    path('record-sale/', views.RecordSaleView.as_view(), name='record_sale'),
    path('collection/', views.CollectionCreateView.as_view(), name='collection'),
    path('handover/', views.HandoverCreateView.as_view(), name='handover'),
    path('statement/', views.StatementView.as_view(), name='statement'),
]
