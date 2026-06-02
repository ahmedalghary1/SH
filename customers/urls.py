from django.urls import path

from . import views

app_name = 'customers'

urlpatterns = [
    path('', views.CustomerListView.as_view(), name='list'),
    path('create/', views.CustomerCreateView.as_view(), name='create'),
    path('<int:pk>/', views.CustomerDetailView.as_view(), name='detail'),
    path('<int:pk>/update/', views.CustomerUpdateView.as_view(), name='update'),
    path('ajax/search/', views.ajax_search_customers, name='ajax_search'),
    path('ajax/quick-create/', views.ajax_quick_create_customer, name='ajax_quick_create'),
]
