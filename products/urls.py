from django.urls import path

from . import views

app_name = 'products'

urlpatterns = [
    path('', views.ProductListView.as_view(), name='list'),
    path('create/', views.ProductCreateView.as_view(), name='create'),
    path('<int:pk>/', views.ProductDetailView.as_view(), name='detail'),
    path('<int:pk>/update/', views.ProductUpdateView.as_view(), name='update'),
    path('<int:pk>/deactivate/', views.ProductDeactivateView.as_view(), name='deactivate'),
    path('ajax/search/', views.ajax_search_products, name='ajax_search'),
    path('ajax/<int:product_id>/variants/', views.ajax_get_product_variants, name='ajax_variants'),
    path('ajax/variant/<int:variant_id>/price/', views.ajax_get_variant_price, name='ajax_price'),
]
