from django.urls import path

from . import views

app_name = 'finance'

urlpatterns = [
    path('cash/', views.CashDashboardView.as_view(), name='cash'),
    path('shift/', views.CashShiftView.as_view(), name='cash_shift'),
    path('shift-close/', views.ShiftCloseView.as_view(), name='shift_close'),
    path('accounts/', views.CashAccountListView.as_view(), name='accounts'),
    path('accounts/create/', views.CashAccountCreateView.as_view(), name='account_create'),
    path('accounts/<int:pk>/', views.CashAccountDetailView.as_view(), name='account_detail'),
    path('accounts/<int:pk>/update/', views.CashAccountUpdateView.as_view(), name='account_update'),
    path('accounts/<int:pk>/delete/', views.CashAccountDeleteView.as_view(), name='account_delete'),
    path('transactions/', views.TransactionListView.as_view(), name='transactions'),
    path('transactions/<int:pk>/delete/', views.PaymentTransactionDeleteView.as_view(), name='transaction_delete'),
    path('transactions/expense/', views.ExpenseCreateView.as_view(), name='expense_create'),
    path('transactions/collection/', views.CustomerCollectionView.as_view(), name='collection_create'),
    path('transactions/supplier-payment/', views.SupplierPaymentView.as_view(), name='supplier_payment_create'),
    path('transactions/transfer/', views.TransferView.as_view(), name='transfer'),
    path('statements/cash-account/', views.CashAccountStatementView.as_view(), name='cash_account_statement'),
    path('statements/customer/', views.CustomerStatementView.as_view(), name='customer_statement'),
    path('statements/sales-rep/', views.SalesRepStatementView.as_view(), name='sales_rep_statement'),
    path('reports/daily-collections/', views.DailyCollectionsReportView.as_view(), name='daily_collections'),
    path('reports/expenses/', views.ExpenseReportView.as_view(), name='expense_report'),
]
