from django.urls import path

from . import views

app_name = 'returns'

urlpatterns = [
    path('', views.SalesReturnListView.as_view(), name='list'),
    path('create/', views.SalesReturnCreateView.as_view(), name='create'),
    path('<int:pk>/', views.SalesReturnDetailView.as_view(), name='detail'),
    path('<int:pk>/items/add/', views.ReturnItemAddView.as_view(), name='add_item'),
    path('<int:pk>/exchange/add/', views.ExchangeItemAddView.as_view(), name='add_exchange'),
    path('<int:pk>/approve/', views.SalesReturnApproveView.as_view(), name='approve'),
    path('<int:pk>/complete/', views.SalesReturnCompleteView.as_view(), name='complete'),
    path('<int:pk>/reject/', views.SalesReturnRejectView.as_view(), name='reject'),
    path('reports/reasons/', views.ReturnReasonReportView.as_view(), name='reason_report'),
    path('reports/products/', views.ProductReturnReportView.as_view(), name='product_report'),
]
