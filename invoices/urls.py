from django.urls import path

from . import views

app_name = 'invoices'

urlpatterns = [
    path('<int:pk>/', views.InvoiceDetailView.as_view(), name='detail'),
    path('<int:pk>/print/', views.InvoicePrintView.as_view(), name='print'),
    path('generate/<int:order_pk>/', views.GenerateInvoiceView.as_view(), name='generate'),
]
