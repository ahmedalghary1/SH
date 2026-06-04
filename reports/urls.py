from django.urls import path

from . import views

app_name = 'reports'

urlpatterns = [
    path('sales/', views.SalesReportView.as_view(), name='sales'),
    path('sales/export/', views.SalesReportExportView.as_view(), name='sales_export'),
    path('profitability/', views.ProfitabilityReportView.as_view(), name='profitability'),
    path('profitability/export/', views.ProfitabilityReportExportView.as_view(), name='profitability_export'),
    path('net-profit/', views.NetProfitReportView.as_view(), name='net_profit'),
    path('customer-debt/', views.CustomerDebtReportView.as_view(), name='customer_debt'),
    path('inactive-customers/', views.InactiveCustomerReportView.as_view(), name='inactive_customers'),
    path('discounts/', views.DiscountReportView.as_view(), name='discounts'),
    path('sales-rep-custody/', views.SalesRepCustodyReportView.as_view(), name='sales_rep_custody'),
    path('sales-rep-collections/', views.SalesRepCollectionsReportView.as_view(), name='sales_rep_collections'),
    path('low-stock/', views.LowStockReportView.as_view(), name='low_stock'),
    path('stale-products/', views.StaleProductsReportView.as_view(), name='stale_products'),
    path('returns/', views.ReturnsReportView.as_view(), name='returns'),
    path('purchases/', views.PurchaseReportAdvancedView.as_view(), name='purchases'),
    path('supplier-dues/', views.SupplierDuesReportView.as_view(), name='supplier_dues'),
    path('daily-sales/', views.DailySalesReportView.as_view(), name='daily_sales'),
    path('monthly-sales/', views.MonthlySalesReportView.as_view(), name='monthly_sales'),
    path('yearly-sales/', views.YearlySalesReportView.as_view(), name='yearly_sales'),
    path('inventory/', views.InventoryReportView.as_view(), name='inventory'),
    path('customers/', views.CustomerReportView.as_view(), name='customers'),
    path('employees/', views.EmployeeSalesReportView.as_view(), name='employees'),
]
