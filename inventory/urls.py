from django.urls import path

from . import views

app_name = 'inventory'

urlpatterns = [
    path('warehouses/', views.WarehouseListView.as_view(), name='warehouses'),
    path('warehouses/create/', views.WarehouseCreateView.as_view(), name='warehouse_create'),
    path('stock/', views.StockListView.as_view(), name='stock'),
    path('movements/', views.StockMovementListView.as_view(), name='movements'),
    path('movements/in/', views.StockInView.as_view(), name='stock_in'),
    path('movements/out/', views.StockOutView.as_view(), name='stock_out'),
    path('movements/transfer/', views.StockTransferView.as_view(), name='transfer'),
    path('movements/representative-issue/', views.RepresentativeIssueView.as_view(), name='representative_issue'),
    path('movements/representative-return/', views.RepresentativeReturnView.as_view(), name='representative_return'),
    path('movements/adjustment/', views.StockAdjustmentView.as_view(), name='adjustment'),
    path('ajax/check-stock/', views.ajax_check_stock, name='ajax_check_stock'),
]
