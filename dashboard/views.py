from django.db.models import Count, F, Sum
from django.shortcuts import redirect
from django.utils import timezone
from django.views.generic import TemplateView

from accounts.permissions import RoleRequiredMixin
from customers.models import Customer
from finance.models import CashAccount, PaymentTransaction
from inventory.models import Stock, StockMovement
from orders.models import Order, OrderItem


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
            orders = Order.objects.filter(created_at__date=today).exclude(status__in=[Order.STATUS_CANCELLED, Order.STATUS_RETURNED])
            context.update({
                'today_sales': orders.aggregate(v=Sum('total'))['v'] or 0,
                'today_cost': orders.aggregate(v=Sum('total_cost'))['v'] or 0,
                'today_gross_profit': orders.aggregate(v=Sum('gross_profit'))['v'] or 0,
                'cash_balance': CashAccount.objects.filter(is_active=True).aggregate(v=Sum('balance'))['v'] or 0,
                'today_expenses': PaymentTransaction.objects.filter(
                    transaction_type=PaymentTransaction.TYPE_EXPENSE,
                    created_at__date=today,
                ).aggregate(v=Sum('amount'))['v'] or 0,
                'today_orders': orders.count(),
                'paid_total': orders.aggregate(v=Sum('paid_amount'))['v'] or 0,
                'remaining_total': orders.aggregate(v=Sum('remaining_amount'))['v'] or 0,
                'low_stocks': Stock.objects.select_related('warehouse', 'variant__product').filter(quantity__lte=F('min_quantity'))[:10],
                'latest_orders': Order.objects.select_related('customer', 'created_by').order_by('-created_at')[:10],
                'top_products': OrderItem.objects.values('variant__product__name').annotate(qty=Sum('quantity')).order_by('-qty')[:10],
                'employee_sales': Order.objects.values('created_by__username').annotate(total=Sum('total'), count=Count('id')).order_by('-total')[:10],
            })
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
