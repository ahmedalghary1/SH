from django.urls import path

from . import views

app_name = 'products'

urlpatterns = [
    path('', views.ProductListView.as_view(), name='list'),
    path('categories/', views.CategoryListView.as_view(), name='categories'),
    path('categories/create/', views.CategoryCreateView.as_view(), name='category_create'),
    path('categories/<int:pk>/update/', views.CategoryUpdateView.as_view(), name='category_update'),
    path('categories/<int:pk>/delete/', views.CategoryDeleteView.as_view(), name='category_delete'),
    path('colors/', views.ColorListView.as_view(), name='colors'),
    path('colors/create/', views.ColorCreateView.as_view(), name='color_create'),
    path('colors/<int:pk>/update/', views.ColorUpdateView.as_view(), name='color_update'),
    path('colors/<int:pk>/delete/', views.ColorDeleteView.as_view(), name='color_delete'),
    path('sizes/', views.SizeListView.as_view(), name='sizes'),
    path('sizes/create/', views.SizeCreateView.as_view(), name='size_create'),
    path('sizes/<int:pk>/update/', views.SizeUpdateView.as_view(), name='size_update'),
    path('sizes/<int:pk>/delete/', views.SizeDeleteView.as_view(), name='size_delete'),
    path('variants/create/', views.ProductVariantCreateView.as_view(), name='variant_create'),
    path('variants/<int:pk>/update/', views.ProductVariantUpdateView.as_view(), name='variant_update'),
    path('variants/<int:pk>/deactivate/', views.ProductVariantDeactivateView.as_view(), name='variant_deactivate'),
    path('variants/<int:pk>/delete/', views.ProductVariantDeleteView.as_view(), name='variant_delete'),
    path('bulk-price-update/', views.BulkPriceUpdateView.as_view(), name='bulk_price_update'),
    path('create/', views.ProductCreateView.as_view(), name='create'),
    path('<int:pk>/movement-report/', views.ProductMovementReportView.as_view(), name='movement_report'),
    path('<int:pk>/', views.ProductDetailView.as_view(), name='detail'),
    path('<int:pk>/update/', views.ProductUpdateView.as_view(), name='update'),
    path('<int:pk>/deactivate/', views.ProductDeactivateView.as_view(), name='deactivate'),
    path('<int:pk>/delete/', views.ProductDeleteView.as_view(), name='delete'),
    path('ajax/search/', views.ajax_search_products, name='ajax_search'),
    path('ajax/quick-create-category/', views.ajax_quick_create_category, name='ajax_quick_create_category'),
    path('ajax/quick-create-color/', views.ajax_quick_create_color, name='ajax_quick_create_color'),
    path('ajax/quick-create-size/', views.ajax_quick_create_size, name='ajax_quick_create_size'),
    path('ajax/quick-create-warehouse/', views.ajax_quick_create_warehouse, name='ajax_quick_create_warehouse'),
    path('ajax/<int:product_id>/variants/', views.ajax_get_product_variants, name='ajax_variants'),
    path('ajax/variant/<int:variant_id>/price/', views.ajax_get_variant_price, name='ajax_price'),
    path('api/categories/', views.api_categories, name='api_categories'),
    path('api/products/', views.api_products, name='api_products'),
]
