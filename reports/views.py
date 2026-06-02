from django.db.models import Count, F, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone
from django.views.generic import TemplateView

from accounts.permissions import ManagerRequiredMixin
from customers.models import Customer
from inventory.models import Stock
from orders.models import Order, OrderItem


class DailySalesReportView(ManagerRequiredMixin, TemplateView):
    template_name = 'reports/daily_sales.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        orders = Order.objects.filter(created_at__date=today).exclude(status__in=[Order.STATUS_CANCELLED, Order.STATUS_RETURNED])
        context['orders_count'] = orders.count()
        context['total_sales'] = orders.aggregate(v=Sum('total'))['v'] or 0
        context['paid_total'] = orders.aggregate(v=Sum('paid_amount'))['v'] or 0
        context['remaining_total'] = orders.aggregate(v=Sum('remaining_amount'))['v'] or 0
        context['top_products'] = OrderItem.objects.filter(order__in=orders).values('variant__product__name').annotate(qty=Sum('quantity')).order_by('-qty')[:10]
        context['employee_sales'] = orders.values('created_by__username').annotate(total=Sum('total'), count=Count('id')).order_by('-total')
        return context


class MonthlySalesReportView(ManagerRequiredMixin, TemplateView):
    template_name = 'reports/monthly_sales.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        orders = Order.objects.exclude(status__in=[Order.STATUS_CANCELLED, Order.STATUS_RETURNED])
        context['months'] = orders.annotate(month=TruncMonth('created_at')).values('month').annotate(total=Sum('total'), count=Count('id')).order_by('-month')
        context['b2b_total'] = orders.filter(order_type=Order.TYPE_B2B).aggregate(v=Sum('total'))['v'] or 0
        context['b2c_total'] = orders.filter(order_type=Order.TYPE_B2C).aggregate(v=Sum('total'))['v'] or 0
        return context


class InventoryReportView(ManagerRequiredMixin, TemplateView):
    template_name = 'reports/inventory.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['stocks'] = Stock.objects.select_related('warehouse', 'variant__product', 'variant__color', 'variant__size')
        context['low_stocks'] = context['stocks'].filter(quantity__lte=F('min_quantity'))
        context['out_stocks'] = context['stocks'].filter(quantity=0)
        return context


class CustomerReportView(ManagerRequiredMixin, TemplateView):
    template_name = 'reports/customers.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['new_customers'] = Customer.objects.order_by('-created_at')[:20]
        context['top_customers'] = Order.objects.values('customer__name', 'customer__phone').annotate(total=Sum('total'), count=Count('id')).order_by('-total')[:20]
        context['debt_customers'] = Order.objects.filter(remaining_amount__gt=0).values('customer__name', 'customer__phone').annotate(remaining=Sum('remaining_amount')).order_by('-remaining')[:20]
        return context


class EmployeeSalesReportView(ManagerRequiredMixin, TemplateView):
    template_name = 'reports/employees.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['employees'] = Order.objects.values('created_by__username').annotate(total=Sum('total'), paid=Sum('paid_amount'), count=Count('id')).order_by('-total')
        return context

# Create your views here.
