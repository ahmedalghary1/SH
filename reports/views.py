import csv

from django.db.models import Avg, Count, F, Sum
from django.db.models.functions import ExtractYear, TruncMonth
from django.http import HttpResponse
from django.utils import timezone
from django.views.generic import TemplateView, View

from accounts.permissions import ManagerRequiredMixin, RoleRequiredMixin
from customers.models import Customer
from finance.models import PaymentTransaction
from inventory.models import Stock
from orders.models import Order, OrderItem
from . import services


class GenericReportMixin:
    template_name = 'reports/generic_report.html'
    report_title = 'Report'

    def get_report(self):
        raise NotImplementedError

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        report = self.get_report()
        context.update(report)
        context.setdefault('title', self.report_title)
        context['filters'] = self.request.GET
        context['summary_pairs'] = list(report.get('summary', {}).items())
        context['table'] = prepare_table(report.get('rows', []))
        context['prepared_sections'] = [
            (title, prepare_table(rows))
            for title, rows in report.get('sections', {}).items()
        ]
        return context


class SalesReportView(RoleRequiredMixin, GenericReportMixin, TemplateView):
    allowed_roles = ('manager', 'sales')
    report_title = 'Sales report'

    def get_report(self):
        return services.sales_report(self.request)


class SalesReportExportView(RoleRequiredMixin, View):
    allowed_roles = ('manager', 'sales')

    def get(self, request):
        report = services.sales_report(request)
        return export_rows('sales-report.csv', report['rows'])


class ProfitabilityReportView(ManagerRequiredMixin, GenericReportMixin, TemplateView):
    report_title = 'Profitability report'

    def get_report(self):
        return services.profitability_report(self.request)


class ProfitabilityReportExportView(ManagerRequiredMixin, View):
    def get(self, request):
        report = services.profitability_report(request)
        rows = report['sections']['profit_by_product']
        return export_rows('profitability-report.csv', rows)


class NetProfitReportView(ManagerRequiredMixin, GenericReportMixin, TemplateView):
    report_title = 'Net profit report'

    def get_report(self):
        return services.net_profit_report(self.request)


class CustomerDebtReportView(ManagerRequiredMixin, GenericReportMixin, TemplateView):
    report_title = 'Customer debt report'

    def get_report(self):
        return services.customer_debt_report()


class InactiveCustomerReportView(ManagerRequiredMixin, GenericReportMixin, TemplateView):
    report_title = 'Inactive customer report'

    def get_report(self):
        days = int(self.request.GET.get('days') or 90)
        return services.inactive_customer_report(days=days)


class DiscountReportView(ManagerRequiredMixin, GenericReportMixin, TemplateView):
    report_title = 'Discount report'

    def get_report(self):
        return services.discount_report(self.request)


class SalesRepCustodyReportView(RoleRequiredMixin, GenericReportMixin, TemplateView):
    allowed_roles = ('manager', 'sales', 'warehouse')
    report_title = 'Sales rep custody report'

    def get_report(self):
        return services.sales_rep_custody_report(self.request)


class SalesRepCollectionsReportView(RoleRequiredMixin, GenericReportMixin, TemplateView):
    allowed_roles = ('manager', 'sales')
    report_title = 'Sales rep collections report'

    def get_report(self):
        return services.sales_rep_collections_report(self.request)


class LowStockReportView(RoleRequiredMixin, GenericReportMixin, TemplateView):
    allowed_roles = ('manager', 'warehouse')
    report_title = 'Low stock report'

    def get_report(self):
        return services.low_stock_report()


class StaleProductsReportView(ManagerRequiredMixin, GenericReportMixin, TemplateView):
    report_title = 'Stale products report'

    def get_report(self):
        days = int(self.request.GET.get('days') or 90)
        return services.stale_products_report(days=days)


class ReturnsReportView(ManagerRequiredMixin, GenericReportMixin, TemplateView):
    report_title = 'Returns report'

    def get_report(self):
        return services.returns_report(self.request)


class PurchaseReportAdvancedView(ManagerRequiredMixin, GenericReportMixin, TemplateView):
    report_title = 'Purchase report'

    def get_report(self):
        return services.purchase_report(self.request)


class SupplierDuesReportView(ManagerRequiredMixin, GenericReportMixin, TemplateView):
    report_title = 'Supplier dues report'

    def get_report(self):
        return services.supplier_dues_report()


def export_rows(filename, rows):
    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response.write('\ufeff')
    writer = csv.writer(response)
    rows = list(rows)
    if not rows:
        writer.writerow(['empty'])
        return response
    headers = list(rows[0].keys())
    writer.writerow(headers)
    for row in rows:
        writer.writerow([row.get(header, '') for header in headers])
    return response


def prepare_table(rows):
    rows = list(rows)
    if not rows:
        return {'headers': [], 'rows': []}
    headers = list(rows[0].keys())
    return {
        'headers': headers,
        'rows': [[row.get(header, '') for header in headers] for row in rows],
    }


class DailySalesReportView(ManagerRequiredMixin, TemplateView):
    template_name = 'reports/daily_sales.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        orders = Order.objects.filter(created_at__date=today).exclude(status__in=[Order.STATUS_CANCELLED, Order.STATUS_RETURNED])
        context['orders_count'] = orders.count()
        context['total_sales'] = orders.aggregate(v=Sum('total'))['v'] or 0
        context['total_cost'] = orders.aggregate(v=Sum('total_cost'))['v'] or 0
        context['gross_profit'] = orders.aggregate(v=Sum('gross_profit'))['v'] or 0
        context['expenses_total'] = PaymentTransaction.objects.filter(
            transaction_type=PaymentTransaction.TYPE_EXPENSE,
            created_at__date=today,
        ).aggregate(v=Sum('amount'))['v'] or 0
        context['net_profit'] = context['gross_profit'] - context['expenses_total']
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
        context['months'] = orders.annotate(month=TruncMonth('created_at')).values('month').annotate(
            total=Sum('total'),
            cost=Sum('total_cost'),
            profit=Sum('gross_profit'),
            count=Count('id'),
        ).order_by('-month')
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
        context['employees'] = Order.objects.values('created_by__username').annotate(
            sales_total=Sum('total'),
            total_cost=Sum('total_cost'),
            gross_profit=Sum('gross_profit'),
            paid=Sum('paid_amount'),
            count=Count('id'),
            avg_order=Avg('total'),
        ).order_by('-sales_total')
        return context


class YearlySalesReportView(ManagerRequiredMixin, TemplateView):
    template_name = 'reports/yearly_sales.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        orders = Order.objects.exclude(status__in=[Order.STATUS_CANCELLED, Order.STATUS_RETURNED])
        context['years'] = orders.annotate(year=ExtractYear('created_at')).values('year').annotate(
            total=Sum('total'),
            cost=Sum('total_cost'),
            profit=Sum('gross_profit'),
            paid=Sum('paid_amount'),
            remaining=Sum('remaining_amount'),
            count=Count('id'),
        ).order_by('-year')
        return context

# Create your views here.
