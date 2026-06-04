from django.db.models import F, Sum
from django.utils import timezone
from django.views.generic import TemplateView

from accounts.permissions import RoleRequiredMixin
from customers.models import Customer
from inventory.models import Stock, StockMovement
from orders.models import Order
from reports.services import manager_dashboard_kpis


class DashboardView(RoleRequiredMixin, TemplateView):
    allowed_roles = ('manager', 'sales', 'warehouse')

    def get_template_names(self):
        role = self.request.user.role
        if self.request.user.is_superuser or role == 'manager':
            return ['dashboard/manager.html']
        if role == 'warehouse':
            return ['dashboard/warehouse.html']
        return ['dashboard/sales.html']

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        user = self.request.user
        if user.is_superuser or user.role == 'manager':
            kpis = manager_dashboard_kpis()
            context.update(kpis)
            context['today_gross_profit'] = kpis['gross_profit']
            context['cash_balance'] = sum(account.balance for account in kpis['cash_accounts'])
            context['paid_total'] = kpis['collections_total']
            context['remaining_total'] = kpis['customer_remaining_total']
        elif user.role == 'warehouse':
            context.update({
                'preparing_orders': Order.objects.filter(status=Order.STATUS_PREPARING).select_related('customer', 'warehouse')[:20],
                'low_stocks': Stock.objects.select_related('warehouse', 'variant__product').filter(quantity__lte=F('min_quantity'))[:10],
                'latest_movements': StockMovement.objects.select_related('variant__product', 'from_warehouse', 'to_warehouse').order_by('-created_at')[:10],
            })
        else:
            my_orders = Order.objects.filter(created_by=user, created_at__date=today)
            context.update({
                'my_orders_today': my_orders.count(),
                'my_sales_today': my_orders.aggregate(v=Sum('total'))['v'] or 0,
                'my_customers': Customer.objects.filter(created_by=user, created_at__date=today).count(),
                'latest_orders': Order.objects.filter(created_by=user).select_related('customer').order_by('-created_at')[:10],
            })
        return context

# Create your views here.
