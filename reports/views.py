import csv

from django.db import models
from django.db.models import Avg, Count, F, Sum
from django.db.models.functions import ExtractYear, TruncMonth
from django.http import HttpResponse
from django.utils import timezone
from django.views.generic import TemplateView, View

from accounts.permissions import ManagerRequiredMixin, RoleRequiredMixin, can_view_costs
from customers.models import Customer
from finance.models import PaymentTransaction
from inventory.models import Stock, StockMovement, Warehouse
from orders.models import Order, OrderItem
from returns.models import SalesReturn
from . import services


MOVEMENT_TYPE_LABELS = {
    StockMovement.TYPE_IN: 'إضافة مخزون',
    StockMovement.TYPE_OUT: 'صرف مخزون',
    StockMovement.TYPE_TRANSFER: 'تحويل بين المخازن',
    StockMovement.TYPE_SALE: 'بيع',
    StockMovement.TYPE_RETURN: 'مرتجع',
    StockMovement.TYPE_ADJUSTMENT: 'تسوية مخزون',
    StockMovement.TYPE_PURCHASE_RECEIVE: 'استلام مشتريات',
    StockMovement.TYPE_SALES_RETURN: 'مرتجع مبيعات',
    StockMovement.TYPE_DAMAGED_RETURN: 'مرتجع تالف',
    StockMovement.TYPE_EXCHANGE_OUT: 'صرف استبدال',
    StockMovement.TYPE_SALES_REP_ASSIGNMENT: 'تسليم عهدة لمندوب',
    StockMovement.TYPE_SALES_REP_RETURN: 'استلام عهدة من مندوب',
    StockMovement.TYPE_SALES_REP_SALE: 'بيع مندوب',
    StockMovement.TYPE_SAMPLE: 'عينة مجانية',
}


REPORT_CARDS = {
    'basic': [
        {
            'title': 'تقرير اليوم',
            'description': 'ملخص سريع لما حدث اليوم.',
            'url_name': 'reports:daily_sales',
            'icon': 'icon-chart',
            'tone': 'sales',
            'roles': ('manager', 'sales'),
            'featured': True,
        },
        {
            'title': 'تقرير المبيعات',
            'description': 'اعرف قيمة المبيعات والفواتير خلال فترة.',
            'url_name': 'reports:sales',
            'icon': 'icon-sale',
            'tone': 'sales',
            'roles': ('manager', 'sales'),
        },
        {
            'title': 'تقرير المخزون',
            'description': 'تابع الكميات المتاحة والمنتجات الناقصة.',
            'url_name': 'reports:inventory',
            'icon': 'icon-warehouse',
            'tone': 'general',
            'roles': ('manager', 'warehouse'),
        },
        {
            'title': 'مديونيات العملاء',
            'description': 'اعرف العملاء الذين لديهم مبالغ متبقية.',
            'url_name': 'reports:customers',
            'icon': 'icon-users',
            'tone': 'general',
            'roles': ('manager',),
        },
        {
            'title': 'مديونيات الموردين',
            'description': 'اعرف المستحقات المطلوب دفعها للموردين.',
            'url_name': 'reports:supplier_dues',
            'icon': 'icon-money',
            'tone': 'manager',
            'roles': ('manager',),
        },
        {
            'title': 'تقرير المرتجعات',
            'description': 'راجع المرتجعات والاستبدالات المسجلة.',
            'url_name': 'reports:returns',
            'icon': 'icon-return',
            'tone': 'risk',
            'roles': ('manager', 'sales'),
        },
        {
            'title': 'تقرير الخزنة',
            'description': 'تابع حركة النقدية والوردية.',
            'url_name': 'finance:cash',
            'icon': 'icon-money',
            'tone': 'sales',
            'roles': ('manager',),
        },
        {
            'title': 'المنتجات الناقصة',
            'description': 'أصناف وصلت إلى حد إعادة الطلب.',
            'url_name': 'reports:low_stock',
            'icon': 'icon-box',
            'tone': 'warning',
            'roles': ('manager', 'warehouse'),
        },
        {
            'title': 'حركة المخزون',
            'description': 'راجع التحويلات والإضافات والصرف.',
            'url_name': 'reports:stock_movement',
            'icon': 'icon-exchange',
            'tone': 'general',
            'roles': ('manager', 'warehouse'),
        },
    ],
    'manager': [
        {
            'title': 'تقرير الأرباح',
            'description': 'اعرف الربح والتكلفة وهامش المكسب.',
            'url_name': 'reports:profitability',
            'icon': 'icon-chart',
            'tone': 'manager',
            'roles': ('manager',),
        },
        {
            'title': 'صافي الربح',
            'description': 'الربح بعد خصم المصروفات.',
            'url_name': 'reports:net_profit',
            'icon': 'icon-money',
            'tone': 'manager',
            'roles': ('manager',),
        },
        {
            'title': 'تقرير الخصومات',
            'description': 'تابع الخصومات وتأثيرها على البيع.',
            'url_name': 'reports:discounts',
            'icon': 'icon-file',
            'tone': 'warning',
            'roles': ('manager',),
        },
        {
            'title': 'أداء الموظفين',
            'description': 'قارن المبيعات والتحصيل لكل موظف.',
            'url_name': 'reports:employees',
            'icon': 'icon-user',
            'tone': 'manager',
            'roles': ('manager',),
        },
        {
            'title': 'المنتجات الراكدة',
            'description': 'أصناف لم تتحرك منذ فترة.',
            'url_name': 'reports:stale_products',
            'icon': 'icon-box',
            'tone': 'secondary',
            'roles': ('manager',),
        },
        {
            'title': 'تقرير المشتريات',
            'description': 'راجع أوامر الشراء والمدفوع والمتبقي.',
            'url_name': 'reports:purchases',
            'icon': 'icon-money',
            'tone': 'secondary',
            'roles': ('manager',),
        },
    ],
}


def _card_visible(user, card):
    if user.is_superuser:
        return True
    return getattr(user, 'role', None) in card['roles']


class ReportsIndexView(RoleRequiredMixin, TemplateView):
    allowed_roles = ('manager', 'sales', 'warehouse')
    template_name = 'reports/index.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['can_view_costs'] = can_view_costs(self.request.user)
        context['basic_reports'] = [
            card for card in REPORT_CARDS['basic']
            if _card_visible(self.request.user, card)
        ]
        context['manager_reports'] = [
            card for card in REPORT_CARDS['manager']
            if _card_visible(self.request.user, card)
        ]
        context['featured_report'] = next(
            (card for card in context['basic_reports'] if card.get('featured')),
            None,
        )
        if context['featured_report']:
            context['basic_reports'] = [
                card for card in context['basic_reports']
                if card is not context['featured_report']
            ]
        return context


class GenericReportMixin:
    template_name = 'reports/generic_report.html'
    report_title = 'تقرير'
    export_name = None

    def get_report(self):
        raise NotImplementedError

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        report = self.get_report()
        context.update(report)
        context.setdefault('title', self.report_title)
        context['description'] = report.get('description') or REPORT_DESCRIPTIONS.get(context['title'], '')
        context['filters'] = self.request.GET
        context['can_view_costs'] = can_view_costs(self.request.user)
        context['summary_pairs'] = [
            (translate_label(key), format_report_value(value))
            for key, value in report.get('summary', {}).items()
        ]
        context['table'] = prepare_table(report.get('rows', []))
        context['prepared_sections'] = [
            (translate_section_title(title), prepare_table(rows))
            for title, rows in report.get('sections', {}).items()
        ]
        context['export_url_name'] = self.export_name
        return context


class SalesReportView(RoleRequiredMixin, GenericReportMixin, TemplateView):
    allowed_roles = ('manager', 'sales')
    report_title = 'تقرير المبيعات'
    export_name = 'reports:sales_export'

    def get_report(self):
        return services.sales_report(self.request)


class SalesReportExportView(RoleRequiredMixin, View):
    allowed_roles = ('manager', 'sales')

    def get(self, request):
        report = services.sales_report(request)
        return export_rows('sales-report.csv', report['rows'])


class ProfitabilityReportView(ManagerRequiredMixin, GenericReportMixin, TemplateView):
    report_title = 'تقرير الأرباح'
    export_name = 'reports:profitability_export'

    def get_report(self):
        return services.profitability_report(self.request)


class ProfitabilityReportExportView(ManagerRequiredMixin, View):
    def get(self, request):
        report = services.profitability_report(request)
        rows = report['sections']['profit_by_product']
        return export_rows('profitability-report.csv', rows)


class NetProfitReportView(ManagerRequiredMixin, GenericReportMixin, TemplateView):
    report_title = 'تقرير صافي الربح'

    def get_report(self):
        return services.net_profit_report(self.request)


class CustomerDebtReportView(ManagerRequiredMixin, GenericReportMixin, TemplateView):
    report_title = 'مديونيات العملاء'

    def get_report(self):
        return services.customer_debt_report()


class InactiveCustomerReportView(ManagerRequiredMixin, GenericReportMixin, TemplateView):
    report_title = 'تقرير العملاء غير النشطين'

    def get_report(self):
        days = int(self.request.GET.get('days') or 90)
        return services.inactive_customer_report(days=days)


class DiscountReportView(ManagerRequiredMixin, GenericReportMixin, TemplateView):
    report_title = 'تقرير الخصومات'

    def get_report(self):
        return services.discount_report(self.request)


class SalesRepCustodyReportView(RoleRequiredMixin, GenericReportMixin, TemplateView):
    allowed_roles = ('manager', 'warehouse')
    report_title = 'تقرير عهدة المندوبين'

    def get_report(self):
        return services.sales_rep_custody_report(self.request)


class SalesRepCollectionsReportView(RoleRequiredMixin, GenericReportMixin, TemplateView):
    allowed_roles = ('manager', 'sales')
    report_title = 'تقرير تحصيلات المندوب'

    def get_report(self):
        return services.sales_rep_collections_report(self.request)


class LowStockReportView(RoleRequiredMixin, GenericReportMixin, TemplateView):
    allowed_roles = ('manager', 'warehouse')
    report_title = 'المنتجات الناقصة'

    def get_report(self):
        return services.low_stock_report()


class StaleProductsReportView(ManagerRequiredMixin, GenericReportMixin, TemplateView):
    report_title = 'المنتجات الراكدة'

    def get_report(self):
        days = int(self.request.GET.get('days') or 90)
        return services.stale_products_report(days=days)


class ReturnsReportView(RoleRequiredMixin, GenericReportMixin, TemplateView):
    allowed_roles = ('manager', 'sales')
    report_title = 'تقرير المرتجعات'

    def get_report(self):
        return services.returns_report(self.request)


class PurchaseReportAdvancedView(ManagerRequiredMixin, GenericReportMixin, TemplateView):
    report_title = 'تقرير المشتريات'

    def get_report(self):
        return services.purchase_report(self.request)


class SupplierDuesReportView(ManagerRequiredMixin, GenericReportMixin, TemplateView):
    report_title = 'مديونيات الموردين'

    def get_report(self):
        return services.supplier_dues_report()


def export_rows(filename, rows):
    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response.write('\ufeff')
    writer = csv.writer(response)
    rows = list(rows)
    if not rows:
        writer.writerow(['لا توجد بيانات'])
        return response
    headers = list(rows[0].keys())
    writer.writerow([translate_label(header) for header in headers])
    for row in rows:
        writer.writerow([format_report_value(row.get(header, '')) for header in headers])
    return response


def prepare_table(rows):
    rows = list(rows)
    if not rows:
        return {'headers': [], 'rows': []}
    headers = list(rows[0].keys())
    translated_headers = [translate_label(h) for h in headers]
    return {
        'headers': translated_headers,
        'rows': [[format_report_value(row.get(header, '')) for header in headers] for row in rows],
    }


LABEL_TRANSLATIONS = {
    'order_number': 'رقم الفاتورة',
    'order__order_number': 'رقم الفاتورة',
    'purchase_number': 'رقم أمر الشراء',
    'date': 'التاريخ',
    'created_at': 'تاريخ التسجيل',
    'order_date': 'تاريخ أمر الشراء',
    'collection_date': 'تاريخ التحصيل',
    'customer': 'العميل',
    'customer__name': 'العميل',
    'customer__phone': 'هاتف العميل',
    'name': 'الاسم',
    'phone': 'الهاتف',
    'customer_type': 'نوع العميل',
    'employee': 'الموظف',
    'created_by__username': 'الموظف',
    'sales_rep__username': 'المندوب',
    'total': 'الإجمالي',
    'total_amount': 'إجمالي القيمة',
    'total_sales': 'إجمالي المبيعات',
    'paid': 'المحصل',
    'paid_amount': 'المدفوع',
    'paid_total': 'إجمالي المدفوع',
    'remaining': 'المتبقي',
    'remaining_amount': 'المتبقي',
    'remaining_total': 'إجمالي المتبقي',
    'discount': 'الخصم',
    'discount_amount': 'قيمة الخصم',
    'discount_percentage': 'نسبة الخصم',
    'discount_reason': 'سبب الخصم',
    'discount_total': 'إجمالي الخصومات',
    'total_discounts': 'إجمالي الخصومات',
    'status': 'الحالة',
    'payment_status': 'حالة الدفع',
    'subtotal': 'الإجمالي قبل الخصم',
    'amount': 'المبلغ',
    'cash_account__name': 'الخزنة',
    'notes': 'ملاحظات',
    'reason': 'السبب',
    'return_type': 'نوع المرتجع',
    'refund_amount': 'قيمة الاسترداد',
    'refund': 'قيمة الاسترداد',
    'product__name': 'المنتج',
    'product__sku': 'كود المنتج',
    'variant__product__name': 'المنتج',
    'variant__product__category__name': 'التصنيف',
    'product_variant__product__name': 'المنتج',
    'quantity': 'الكمية',
    'quantity_assigned': 'الكمية المسلمة',
    'quantity_sold': 'الكمية المباعة',
    'quantity_returned': 'الكمية المرتجعة',
    'quantity_remaining': 'الرصيد المتبقي',
    'qty': 'الكمية',
    'count': 'العدد',
    'count__id': 'العدد',
    'orders': 'عدد الفواتير',
    'month': 'الشهر',
    'year': 'السنة',
    'warehouse__name': 'المخزن',
    'source_warehouse__name': 'مخزن الصرف',
    'supplier__name': 'المورد',
    'variant_sku': 'كود اللون/المقاس',
    'variant__variant_sku': 'كود اللون/المقاس',
    'barcode': 'الباركود',
    'company_name': 'اسم الشركة',
    'opening_balance': 'الرصيد الافتتاحي',
    'current_balance': 'الرصيد الحالي',
    'credit_limit': 'حد الائتمان',
    'purchases': 'إجمالي المشتريات',
    'total_cost': 'إجمالي التكلفة',
    'cost': 'التكلفة',
    'cost_price': 'سعر التكلفة',
    'sale_price': 'سعر البيع',
    'gross_profit': 'مجمل الربح',
    'profit': 'الربح',
    'profit_margin': 'هامش الربح',
    'expenses': 'المصروفات',
    'net_profit': 'صافي الربح',
    'total_debt': 'إجمالي المديونية',
    'days': 'عدد الأيام',
    'customers': 'عدد العملاء',
    'assigned': 'إجمالي المسلم',
    'sold': 'إجمالي المباع',
    'returned': 'إجمالي المرتجع',
    'collected': 'إجمالي التحصيل',
    'handed_over_amount': 'المبلغ المسلم',
    'handed_over': 'تم التسليم',
    'items': 'عدد الأصناف',
    'variants': 'عدد المتغيرات',
    'returns': 'عدد المرتجعات',
    'suppliers': 'عدد الموردين',
    'total_due': 'إجمالي المستحق',
    'min_quantity': 'الحد الأدنى',
    'is_active': 'الحالة',
}


SECTION_TRANSLATIONS = {
    'profit_by_product': 'الربحية حسب المنتج',
    'profit_by_category': 'الربحية حسب التصنيف',
    'profit_by_employee': 'الربحية حسب الموظف',
    'profit_by_customer': 'الربحية حسب العميل',
    'top_reasons': 'أكثر أسباب المرتجعات تكرارًا',
    'top_products': 'أكثر المنتجات المرتجعة',
}


VALUE_TRANSLATIONS = {
    'b2c': 'قطاعي',
    'b2b': 'جملة',
    'retail': 'قطاعي',
    'wholesale': 'جملة',
    'draft': 'مسودة',
    'confirmed': 'مؤكدة',
    'preparing': 'قيد التجهيز',
    'ready': 'جاهزة',
    'completed': 'مكتملة',
    'cancelled': 'ملغاة',
    'returned': 'مرتجعة',
    'partially_returned': 'مرتجعة جزئيًا',
    'paid': 'مدفوعة',
    'partial': 'مدفوعة جزئيًا',
    'unpaid': 'غير مدفوعة',
    'exchange': 'استبدال',
    'refund': 'استرداد',
    'cash': 'نقدي',
    'wallet_transfer': 'تحويل محفظة',
    'bank_transfer': 'تحويل بنكي',
    'credit': 'آجل',
    'cod': 'دفع عند الاستلام',
}


REPORT_DESCRIPTIONS = {
    'تقرير المبيعات': 'يعرض مبيعات المحل أو مبيعاتك خلال فترة محددة.',
    'تقرير الأرباح': 'يوضح الربح والتكلفة وهامش المكسب للمدير.',
    'تقرير صافي الربح': 'يعرض صافي الربح بعد خصم المصروفات.',
    'مديونيات العملاء': 'يوضح العملاء الذين لديهم مبالغ مستحقة.',
    'تقرير العملاء غير النشطين': 'يعرض العملاء الذين لم يشتروا منذ فترة.',
    'تقرير الخصومات': 'يتابع الخصومات الممنوحة وتأثيرها على المبيعات.',
    'تقرير عهدة المندوبين': 'يوضح الكميات المسلمة والمباعة والمتبقية مع المندوبين.',
    'تقرير تحصيلات المندوب': 'يعرض المبالغ التي حصلها المندوبون وسلموها.',
    'المنتجات الناقصة': 'يعرض الأصناف التي وصلت إلى حد إعادة الطلب.',
    'المنتجات الراكدة': 'يعرض الأصناف التي لم تتحرك منذ فترة.',
    'تقرير المرتجعات': 'يعرض المرتجعات والاستبدالات خلال الفترة المحددة.',
    'تقرير المشتريات': 'يعرض أوامر الشراء وإجمالي المدفوع والمتبقي.',
    'مديونيات الموردين': 'يوضح الموردين الذين لهم مبالغ مستحقة.',
}


def translate_label(key):
    return LABEL_TRANSLATIONS.get(key, key.replace('__', ' / ').replace('_', ' '))


def translate_section_title(title):
    return SECTION_TRANSLATIONS.get(title, translate_label(title))


def format_report_value(value):
    if value is True:
        return 'نعم'
    if value is False:
        return 'لا'
    if value is None:
        return ''
    return VALUE_TRANSLATIONS.get(str(value), value)


class DailySalesReportView(RoleRequiredMixin, TemplateView):
    allowed_roles = ('manager', 'sales')
    template_name = 'reports/daily_sales.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        orders = Order.objects.filter(created_at__date=today).exclude(status__in=services.EXCLUDED_SALES_STATUSES)
        returns = SalesReturn.objects.filter(created_at__date=today)
        transactions = PaymentTransaction.objects.filter(transaction_date=today)
        if getattr(self.request.user, 'role', None) == 'sales' and not self.request.user.is_superuser:
            orders = orders.filter(created_by=self.request.user)
            returns = returns.filter(created_by=self.request.user)
            transactions = transactions.filter(
                models.Q(created_by=self.request.user) |
                models.Q(related_sales_rep=self.request.user)
            )
        context['orders_count'] = orders.count()
        context['total_sales'] = orders.aggregate(v=Sum('total'))['v'] or 0
        context['returns_count'] = returns.count()
        context['returns_total'] = returns.aggregate(v=Sum('refund_amount'))['v'] or 0
        context['collections_total'] = transactions.filter(
            transaction_type__in=[
                PaymentTransaction.TYPE_CUSTOMER_PAYMENT,
                PaymentTransaction.TYPE_SALES_REP_COLLECTION,
            ],
            direction=PaymentTransaction.DIRECTION_IN,
        ).aggregate(v=Sum('amount'))['v'] or 0
        context['expenses_total'] = transactions.filter(
            transaction_type=PaymentTransaction.TYPE_EXPENSE,
            direction=PaymentTransaction.DIRECTION_OUT,
        ).aggregate(v=Sum('amount'))['v'] or 0
        context['supplier_payments_total'] = transactions.filter(
            transaction_type=PaymentTransaction.TYPE_SUPPLIER_PAYMENT,
            direction=PaymentTransaction.DIRECTION_OUT,
        ).aggregate(v=Sum('amount'))['v'] or 0
        context['net_cash'] = (
            (transactions.filter(direction=PaymentTransaction.DIRECTION_IN).aggregate(v=Sum('amount'))['v'] or 0) -
            (transactions.filter(direction=PaymentTransaction.DIRECTION_OUT).aggregate(v=Sum('amount'))['v'] or 0)
        )
        context['can_view_costs'] = can_view_costs(self.request.user)
        if can_view_costs(self.request.user):
            context['total_cost'] = orders.aggregate(v=Sum('total_cost'))['v'] or 0
            context['gross_profit'] = orders.aggregate(v=Sum('gross_profit'))['v'] or 0
            context['net_profit'] = context['gross_profit'] - context['expenses_total']
            context['low_stocks_count'] = Stock.objects.filter(quantity__lte=F('min_quantity')).count()
        context['paid_total'] = orders.aggregate(v=Sum('paid_amount'))['v'] or 0
        context['remaining_total'] = orders.aggregate(v=Sum('remaining_amount'))['v'] or 0
        context['top_products'] = OrderItem.objects.filter(order__in=orders).values('variant__product__name').annotate(qty=Sum('quantity')).order_by('-qty')[:10]
        context['employee_sales'] = orders.values('created_by__username').annotate(total=Sum('total'), count=Count('id')).order_by('-total')
        return context


class MonthlySalesReportView(ManagerRequiredMixin, TemplateView):
    template_name = 'reports/monthly_sales.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        orders = Order.objects.exclude(status__in=services.EXCLUDED_SALES_STATUSES)
        context['can_view_costs'] = can_view_costs(self.request.user)
        if can_view_costs(self.request.user):
            context['months'] = orders.annotate(month=TruncMonth('created_at')).values('month').annotate(
                total=Sum('total'),
                cost=Sum('total_cost'),
                profit=Sum('gross_profit'),
                count=Count('id'),
            ).order_by('-month')
        else:
            context['months'] = orders.annotate(month=TruncMonth('created_at')).values('month').annotate(
                total=Sum('total'),
                count=Count('id'),
            ).order_by('-month')
        context['b2b_total'] = orders.filter(order_type=Order.TYPE_B2B).aggregate(v=Sum('total'))['v'] or 0
        context['b2c_total'] = orders.filter(order_type=Order.TYPE_B2C).aggregate(v=Sum('total'))['v'] or 0
        return context


class InventoryReportView(RoleRequiredMixin, TemplateView):
    allowed_roles = ('manager', 'warehouse')
    template_name = 'reports/inventory.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['can_view_costs'] = can_view_costs(self.request.user)
        context['stocks'] = Stock.objects.select_related('warehouse', 'variant__product', 'variant__color', 'variant__size')
        context['low_stocks'] = context['stocks'].filter(quantity__lte=F('min_quantity'))
        context['out_stocks'] = context['stocks'].filter(quantity=0)
        return context


class CustomerReportView(ManagerRequiredMixin, TemplateView):
    template_name = 'reports/customers.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['can_view_costs'] = can_view_costs(self.request.user)
        valid_orders = Order.objects.exclude(status__in=services.EXCLUDED_SALES_STATUSES)
        context['new_customers'] = Customer.objects.order_by('-created_at')[:20]
        context['top_customers'] = valid_orders.values('customer__name', 'customer__phone').annotate(total=Sum('total'), count=Count('id')).order_by('-total')[:20]
        context['debt_customers'] = valid_orders.filter(remaining_amount__gt=0).values('customer__name', 'customer__phone').annotate(remaining=Sum('remaining_amount')).order_by('-remaining')[:20]
        return context


class EmployeeSalesReportView(ManagerRequiredMixin, TemplateView):
    template_name = 'reports/employees.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        orders = Order.objects.exclude(status__in=services.EXCLUDED_SALES_STATUSES)
        context['can_view_costs'] = can_view_costs(self.request.user)
        if can_view_costs(self.request.user):
            context['employees'] = orders.values('created_by__username').annotate(
                sales_total=Sum('total'),
                total_cost=Sum('total_cost'),
                gross_profit=Sum('gross_profit'),
                paid=Sum('paid_amount'),
                count=Count('id'),
                avg_order=Avg('total'),
            ).order_by('-sales_total')
        else:
            context['employees'] = orders.values('created_by__username').annotate(
                sales_total=Sum('total'),
                paid=Sum('paid_amount'),
                count=Count('id'),
                avg_order=Avg('total'),
            ).order_by('-sales_total')
        return context


class YearlySalesReportView(ManagerRequiredMixin, TemplateView):
    template_name = 'reports/yearly_sales.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        orders = Order.objects.exclude(status__in=services.EXCLUDED_SALES_STATUSES)
        context['can_view_costs'] = can_view_costs(self.request.user)
        if can_view_costs(self.request.user):
            context['years'] = orders.annotate(year=ExtractYear('created_at')).values('year').annotate(
                total=Sum('total'),
                cost=Sum('total_cost'),
                profit=Sum('gross_profit'),
                paid=Sum('paid_amount'),
                remaining=Sum('remaining_amount'),
                count=Count('id'),
            ).order_by('-year')
        else:
            context['years'] = orders.annotate(year=ExtractYear('created_at')).values('year').annotate(
                total=Sum('total'),
                paid=Sum('paid_amount'),
                remaining=Sum('remaining_amount'),
                count=Count('id'),
            ).order_by('-year')
        return context


class StockMovementReportView(RoleRequiredMixin, TemplateView):
    allowed_roles = ('manager', 'warehouse')
    template_name = 'reports/stock_movement.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['can_view_costs'] = can_view_costs(self.request.user)
        movements = StockMovement.objects.select_related(
            'variant__product', 'variant__color', 'variant__size',
            'from_warehouse', 'to_warehouse', 'created_by'
        ).order_by('-created_at')
        
        # Filtering
        date_from = self.request.GET.get('date_from')
        date_to = self.request.GET.get('date_to')
        warehouse_id = self.request.GET.get('warehouse')
        movement_type = self.request.GET.get('movement_type')
        q = self.request.GET.get('q', '').strip()
        
        if date_from:
            movements = movements.filter(created_at__date__gte=date_from)
        if date_to:
            movements = movements.filter(created_at__date__lte=date_to)
        if warehouse_id:
            movements = movements.filter(
                models.Q(from_warehouse_id=warehouse_id) | models.Q(to_warehouse_id=warehouse_id)
            )
        if movement_type:
            movements = movements.filter(movement_type=movement_type)
        if q:
            movements = movements.filter(
                models.Q(variant__product__name__icontains=q) |
                models.Q(variant__product__sku__icontains=q) |
                models.Q(variant__variant_sku__icontains=q)
            )
        
        movement_rows = list(movements[:500])
        for movement in movement_rows:
            movement.report_movement_type = MOVEMENT_TYPE_LABELS.get(
                movement.movement_type,
                movement.get_movement_type_display(),
            )
        context['movements'] = movement_rows
        context['warehouses'] = Warehouse.objects.filter(is_active=True)
        context['movement_types'] = [
            (value, MOVEMENT_TYPE_LABELS.get(value, label))
            for value, label in StockMovement.MOVEMENT_TYPE_CHOICES
        ]
        context['filters'] = {
            'date_from': date_from,
            'date_to': date_to,
            'warehouse': warehouse_id,
            'movement_type': movement_type,
            'q': q,
        }
        return context

# Create your views here.
