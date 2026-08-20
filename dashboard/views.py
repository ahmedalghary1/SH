from django.db.models import F, Sum
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView

from accounts.permissions import RoleRequiredMixin, can_view_costs
from customers.models import Customer
from inventory.models import Stock, StockMovement, Warehouse
from orders.models import Order
from reports.services import manager_dashboard_kpis


class DashboardView(RoleRequiredMixin, TemplateView):
    allowed_roles = ('manager', 'sales', 'warehouse')

    def get_template_names(self):
        role = self.request.user.role
        if self.request.user.is_superuser or role in {'manager', 'director'}:
            return ['dashboard/manager.html']
        if role == 'warehouse':
            return ['dashboard/warehouse.html']
        return ['dashboard/sales.html']

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['can_view_costs'] = can_view_costs(self.request.user)
        today = timezone.localdate()
        user = self.request.user
        if user.is_superuser or user.role in {'manager', 'director'}:
            context['workflow_title'] = 'من الخام إلى الفاتورة'
            context['workflow_actions'] = [
                {'label': 'شراء خام', 'href': reverse('purchases:raw_purchase'), 'icon': 'icon-money'},
                {'label': 'إضافة منتج', 'href': reverse('products:create'), 'icon': 'icon-box'},
                {'label': 'إدخال مخزون', 'href': reverse('inventory:stock_in'), 'icon': 'icon-warehouse'},
                {'label': 'فاتورة بيع', 'href': reverse('orders:create'), 'icon': 'icon-sale'},
                {'label': 'الفواتير', 'href': reverse('invoices:list'), 'icon': 'icon-invoice'},
            ]
            kpis = manager_dashboard_kpis()
            context.update(kpis)
            context['today_gross_profit'] = kpis['gross_profit']
            context['cash_balance'] = sum(account.balance for account in kpis['cash_accounts'])
            context['paid_total'] = kpis['collections_total']
            context['remaining_total'] = kpis['customer_remaining_total']
            
            # Low stock notifications for manager
            warehouse_filter = self.request.GET.get('warehouse')
            low_stocks = Stock.objects.select_related('warehouse', 'variant__product').filter(quantity__lte=F('min_quantity'))
            if warehouse_filter:
                low_stocks = low_stocks.filter(warehouse_id=warehouse_filter)
            context['low_stocks'] = low_stocks[:20]
            context['warehouses'] = Warehouse.objects.filter(is_active=True)
        elif user.role == 'warehouse':
            context['workflow_title'] = 'المخزون اليوم'
            context['workflow_actions'] = [
                {'label': 'إدخال مخزون', 'href': reverse('inventory:stock_in'), 'icon': 'icon-plus'},
                {'label': 'تحويل مخزون', 'href': reverse('inventory:transfer'), 'icon': 'icon-arrow'},
                {'label': 'تسليم مندوب', 'href': reverse('inventory:representative_issue'), 'icon': 'icon-users'},
                {'label': 'المنتجات', 'href': reverse('products:list'), 'icon': 'icon-box'},
                {'label': 'المخزون', 'href': reverse('inventory:stock'), 'icon': 'icon-warehouse'},
            ]
            context.update({
                'preparing_orders': Order.objects.filter(status=Order.STATUS_PREPARING).select_related('customer', 'warehouse')[:20],
                'low_stocks': Stock.objects.select_related('warehouse', 'variant__product').filter(quantity__lte=F('min_quantity'))[:10],
                'latest_movements': StockMovement.objects.select_related('variant__product', 'from_warehouse', 'to_warehouse').order_by('-created_at')[:10],
            })
        else:
            context['workflow_title'] = 'بيع سريع'
            context['workflow_actions'] = [
                {'label': 'فاتورة جديدة', 'href': reverse('orders:create'), 'icon': 'icon-sale'},
                {'label': 'عميل جديد', 'href': reverse('customers:create'), 'icon': 'icon-users'},
                {'label': 'الفواتير', 'href': reverse('invoices:list'), 'icon': 'icon-invoice'},
                {'label': 'العملاء', 'href': reverse('customers:list'), 'icon': 'icon-users'},
            ]
            my_orders = Order.objects.filter(created_by=user, created_at__date=today).exclude(status=Order.STATUS_DRAFT)
            context.update({
                'my_orders_today': my_orders.count(),
                'my_sales_today': my_orders.aggregate(v=Sum('total'))['v'] or 0,
                'my_customers': Customer.objects.filter(created_by=user, created_at__date=today).count(),
                'latest_orders': Order.objects.filter(created_by=user).exclude(status=Order.STATUS_DRAFT).select_related('customer').order_by('-created_at')[:10],
            })
        return context

# Create your views here.
