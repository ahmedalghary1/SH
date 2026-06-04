from django.urls import path

from . import views

app_name = 'customers'

urlpatterns = [
    path('', views.CustomerListView.as_view(), name='list'),
    path('create/', views.CustomerCreateView.as_view(), name='create'),
    path('crm/', views.CRMDashboardView.as_view(), name='crm'),
    path('interactions/today/', views.TodayInteractionsView.as_view(), name='interactions_today'),
    path('reports/top-customers/', views.TopCustomersReportView.as_view(), name='report_top_customers'),
    path('reports/inactive/', views.InactiveCustomersReportView.as_view(), name='report_inactive'),
    path('reports/debtors/', views.DebtorsReportView.as_view(), name='report_debtors'),
    path('reports/complaints/', views.ComplaintsReportView.as_view(), name='report_complaints'),
    path('<int:pk>/', views.CustomerDetailView.as_view(), name='detail'),
    path('<int:pk>/crm/', views.CustomerCRMDetailView.as_view(), name='crm_detail'),
    path('<int:pk>/update/', views.CustomerUpdateView.as_view(), name='update'),
    path('<int:pk>/interactions/', views.CustomerInteractionListView.as_view(), name='interactions'),
    path('<int:pk>/interactions/create/', views.CustomerInteractionCreateView.as_view(), name='interaction_create'),
    path('<int:pk>/interactions/<int:interaction_id>/edit/', views.CustomerInteractionUpdateView.as_view(), name='interaction_edit'),
    path('<int:pk>/interactions/<int:interaction_id>/complete/', views.complete_interaction, name='interaction_complete'),
    path('ajax/search/', views.ajax_search_customers, name='ajax_search'),
    path('ajax/quick-create/', views.ajax_quick_create_customer, name='ajax_quick_create'),
]
