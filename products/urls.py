from django.urls import path

from . import views

app_name = 'products'

urlpatterns = [
    path('', views.ProductListView.as_view(), name='list'),
    path('categories/', views.CategoryListView.as_view(), name='categories'),
    path('categories/create/', views.CategoryCreateView.as_view(), name='category_create'),
    path('categories/<int:pk>/update/', views.CategoryUpdateView.as_view(), name='category_update'),
    path('colors/', views.ColorListView.as_view(), name='colors'),
    path('colors/create/', views.ColorCreateView.as_view(), name='color_create'),
    path('colors/<int:pk>/update/', views.ColorUpdateView.as_view(), name='color_update'),
    path('sizes/', views.SizeListView.as_view(), name='sizes'),
    path('sizes/create/', views.SizeCreateView.as_view(), name='size_create'),
    path('sizes/<int:pk>/update/', views.SizeUpdateView.as_view(), name='size_update'),
    path('variants/create/', views.ProductVariantCreateView.as_view(), name='variant_create'),
    path('variants/<int:pk>/update/', views.ProductVariantUpdateView.as_view(), name='variant_update'),
    path('variants/<int:pk>/deactivate/', views.ProductVariantDeactivateView.as_view(), name='variant_deactivate'),
    path('create/', views.ProductCreateView.as_view(), name='create'),
    path('<int:pk>/', views.ProductDetailView.as_view(), name='detail'),
    path('<int:pk>/update/', views.ProductUpdateView.as_view(), name='update'),
    path('<int:pk>/deactivate/', views.ProductDeactivateView.as_view(), name='deactivate'),
    path('ajax/search/', views.ajax_search_products, name='ajax_search'),
    path('ajax/<int:product_id>/variants/', views.ajax_get_product_variants, name='ajax_variants'),
    path('ajax/variant/<int:variant_id>/price/', views.ajax_get_variant_price, name='ajax_price'),
    path('api/categories/', views.api_categories, name='api_categories'),
    path('api/products/', views.api_products, name='api_products'),
]
