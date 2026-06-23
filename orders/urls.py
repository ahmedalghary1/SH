from django.urls import path

from . import views

app_name = 'orders'

urlpatterns = [
    path('', views.OrderListView.as_view(), name='list'),
    path('retail/', views.RetailOrderListView.as_view(), name='retail_list'),
    path('wholesale/', views.WholesaleOrderListView.as_view(), name='wholesale_list'),
    path('quotes/', views.QuoteListView.as_view(), name='quote_list'),
    path('create/', views.OrderCreateView.as_view(), name='create'),
    path('<int:pk>/', views.OrderDetailView.as_view(), name='detail'),
    path('<int:pk>/update/', views.OrderUpdateView.as_view(), name='update'),
    path('<int:pk>/confirm/', views.OrderConfirmView.as_view(), name='confirm'),
    path('<int:pk>/cancel/', views.OrderCancelView.as_view(), name='cancel'),
    path('<int:pk>/return/', views.OrderReturnView.as_view(), name='return'),
    path('<int:pk>/status/', views.OrderStatusUpdateView.as_view(), name='status_update'),
    path('<int:pk>/delete/', views.OrderDeleteView.as_view(), name='delete'),
    path('ajax/search-products/', views.ajax_search_products, name='ajax_search_products'),
    path('ajax/products/<int:product_id>/variants/', views.ajax_get_product_variants, name='ajax_get_product_variants'),
    path('ajax/variants/<int:variant_id>/stock/', views.ajax_get_variant_stock, name='ajax_get_variant_stock'),
    path('ajax/variants/<int:variant_id>/price/', views.ajax_get_variant_price, name='ajax_get_variant_price'),
    path('ajax/search-customers/', views.ajax_search_customers, name='ajax_search_customers'),
    path('ajax/calculate/', views.ajax_calculate_order_totals, name='ajax_calculate'),
]
