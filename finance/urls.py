from django.urls import path

from . import views

app_name = 'finance'

urlpatterns = [
    path('accounts/', views.CashAccountListView.as_view(), name='accounts'),
    path('accounts/create/', views.CashAccountCreateView.as_view(), name='account_create'),
    path('accounts/<int:pk>/', views.CashAccountDetailView.as_view(), name='account_detail'),
    path('transactions/', views.TransactionListView.as_view(), name='transactions'),
    path('transactions/expense/', views.ExpenseCreateView.as_view(), name='expense_create'),
    path('transactions/collection/', views.CustomerCollectionView.as_view(), name='collection_create'),
    path('transactions/transfer/', views.TransferView.as_view(), name='transfer'),
    path('statements/customer/', views.CustomerStatementView.as_view(), name='customer_statement'),
    path('statements/sales-rep/', views.SalesRepStatementView.as_view(), name='sales_rep_statement'),
    path('reports/daily-collections/', views.DailyCollectionsReportView.as_view(), name='daily_collections'),
    path('reports/expenses/', views.ExpenseReportView.as_view(), name='expense_report'),
]
