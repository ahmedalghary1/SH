from django.urls import path

from . import views

app_name = 'invoices'

urlpatterns = [
    path('', views.InvoiceListView.as_view(), name='list'),
    path('export/excel/', views.InvoiceExcelExportView.as_view(), name='export_excel'),
    path('export/pdf/', views.InvoicePDFExportView.as_view(), name='export_pdf'),
    path('export/print/', views.InvoiceReportPrintView.as_view(), name='report_print'),
    path('<int:pk>/', views.InvoiceDetailView.as_view(), name='detail'),
    path('<int:pk>/print/', views.InvoicePrintView.as_view(), name='print'),
    path('generate/<int:order_pk>/', views.GenerateInvoiceView.as_view(), name='generate'),
]
