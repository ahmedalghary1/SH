from django.urls import path

from . import views

app_name = 'purchases'

urlpatterns = [
    path('suppliers/', views.SupplierListView.as_view(), name='suppliers'),
    path('suppliers/create/', views.SupplierCreateView.as_view(), name='supplier_create'),
    path('suppliers/<int:pk>/', views.SupplierDetailView.as_view(), name='supplier_detail'),
    path('suppliers/<int:pk>/edit/', views.SupplierUpdateView.as_view(), name='supplier_update'),
    path('suppliers/<int:pk>/statement/', views.SupplierStatementView.as_view(), name='supplier_statement'),
    path('orders/', views.PurchaseOrderListView.as_view(), name='orders'),
    path('orders/create/', views.PurchaseOrderCreateView.as_view(), name='order_create'),
    path('orders/<int:pk>/', views.PurchaseOrderDetailView.as_view(), name='order_detail'),
    path('orders/<int:pk>/receive/', views.PurchaseReceiveView.as_view(), name='order_receive'),
    path('orders/<int:pk>/pay/', views.SupplierPaymentView.as_view(), name='order_pay'),
    path('orders/<int:pk>/cancel/', views.PurchaseOrderCancelView.as_view(), name='order_cancel'),
    path('reports/purchases/', views.PurchaseReportView.as_view(), name='purchase_report'),
    path('reports/supplier-dues/', views.SupplierDueReportView.as_view(), name='supplier_due_report'),
]
