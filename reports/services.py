from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, F, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from customers.models import Customer
from finance.models import CashAccount, PaymentTransaction
from inventory.models import Stock
from orders.models import Order, OrderItem
from products.models import ProductVariant
from purchases.models import PurchaseOrder, Supplier
from returns.models import SalesReturn, SalesReturnItem
from sales_reps.models import SalesRepCollection, SalesRepStockAssignment


ZERO = Decimal('0.00')
EXCLUDED_SALES_STATUSES = [Order.STATUS_CANCELLED]


def _sum(queryset, field):
    return queryset.aggregate(v=Sum(field))['v'] or ZERO


def _count(queryset):
    return queryset.count()


def date_range_from_request(request):
    today = timezone.localdate()
    date_from = request.GET.get('date_from') or ''
    date_to = request.GET.get('date_to') or ''
    return {
        'date_from': date_from,
        'date_to': date_to,
        'parsed_from': _parse_date(date_from),
        'parsed_to': _parse_date(date_to),
        'today': today,
        'month_start': today.replace(day=1),
    }


def _parse_date(value):
    if not value:
        return None
    try:
        return timezone.datetime.fromisoformat(value).date()
    except ValueError:
        return None


def apply_order_filters(qs, request, *, restrict_to_user=False):
    dates = date_range_from_request(request)
    if dates['parsed_from']:
        qs = qs.filter(created_at__date__gte=dates['parsed_from'])
    if dates['parsed_to']:
        qs = qs.filter(created_at__date__lte=dates['parsed_to'])
    if restrict_to_user:
        qs = qs.filter(created_by=request.user)
    customer = request.GET.get('customer')
    employee = request.GET.get('employee')
    status = request.GET.get('status')
    payment_status = request.GET.get('payment_status')
    customer_type = request.GET.get('customer_type')
    if customer:
        qs = qs.filter(customer_id=customer)
    if employee:
        qs = qs.filter(created_by_id=employee)
    if status:
        qs = qs.filter(status=status)
    if payment_status:
        qs = qs.filter(payment_status=payment_status)
    if customer_type:
        qs = qs.filter(customer__customer_type=customer_type)
    return qs


def visible_orders_for_user(user):
    qs = Order.objects.select_related('customer', 'created_by', 'warehouse').order_by('-created_at')
    if getattr(user, 'role', None) == 'sales' and not user.is_superuser:
        qs = qs.filter(created_by=user)
    return qs


def sales_report(request):
    qs = apply_order_filters(visible_orders_for_user(request.user), request)
    rows = []
    for order in qs[:300]:
        rows.append({
            'order_number': order.order_number,
            'date': order.created_at.date(),
            'customer': order.customer or '',
            'employee': order.created_by or '',
            'total': order.total,
            'paid': order.paid_amount,
            'remaining': order.remaining_amount,
            'discount': order.discount,
            'status': order.get_status_display(),
            'payment_status': order.get_payment_status_display(),
        })
    return {
        'title': 'Sales report',
        'rows': rows,
        'summary': {
            'orders': qs.count(),
            'total_sales': _sum(qs, 'total'),
            'paid_total': _sum(qs, 'paid_amount'),
            'remaining_total': _sum(qs, 'remaining_amount'),
            'discount_total': _sum(qs, 'discount'),
        },
    }


def profitability_report(request):
    orders = apply_order_filters(
        Order.objects.exclude(status__in=EXCLUDED_SALES_STATUSES).select_related('customer', 'created_by'),
        request,
    )
    sales_total = _sum(orders, 'total')
    gross_profit = _sum(orders, 'gross_profit')
    margin = (gross_profit / sales_total * 100) if sales_total else ZERO
    return {
        'title': 'Profitability report',
        'summary': {
            'total_sales': sales_total,
            'total_cost': _sum(orders, 'total_cost'),
            'total_discounts': _sum(orders, 'discount'),
            'gross_profit': gross_profit,
            'profit_margin': round(margin, 2),
        },
        'sections': {
            'profit_by_product': list(OrderItem.objects.filter(order__in=orders).values(
                'variant__product__name',
            ).annotate(total=Sum('total'), cost=Sum('cost_total'), profit=Sum('profit_total')).order_by('-profit')[:50]),
            'profit_by_category': list(OrderItem.objects.filter(order__in=orders).values(
                'variant__product__category__name',
            ).annotate(total=Sum('total'), cost=Sum('cost_total'), profit=Sum('profit_total')).order_by('-profit')[:50]),
            'profit_by_employee': list(orders.values('created_by__username').annotate(
                total=Sum('total'), cost=Sum('total_cost'), profit=Sum('gross_profit'), orders=Count('id'),
            ).order_by('-profit')[:50]),
            'profit_by_customer': list(orders.values('customer__name', 'customer__phone').annotate(
                total=Sum('total'), cost=Sum('total_cost'), profit=Sum('gross_profit'), orders=Count('id'),
            ).order_by('-profit')[:50]),
        },
    }


def net_profit_report(request):
    orders = apply_order_filters(Order.objects.exclude(status__in=EXCLUDED_SALES_STATUSES), request)
    expenses = PaymentTransaction.objects.filter(transaction_type=PaymentTransaction.TYPE_EXPENSE)
    dates = date_range_from_request(request)
    if dates['parsed_from']:
        expenses = expenses.filter(created_at__date__gte=dates['parsed_from'])
    if dates['parsed_to']:
        expenses = expenses.filter(created_at__date__lte=dates['parsed_to'])
    gross_profit = _sum(orders, 'gross_profit')
    expenses_total = _sum(expenses, 'amount')
    return {
        'title': 'Net profit report',
        'summary': {
            'gross_profit': gross_profit,
            'expenses': expenses_total,
            'net_profit': gross_profit - expenses_total,
        },
        'rows': list(expenses.select_related('cash_account', 'created_by').values(
            'created_at', 'amount', 'cash_account__name', 'notes', 'created_by__username',
        )[:200]),
    }


def customer_debt_report():
    qs = Customer.objects.filter(
        Q(order__remaining_amount__gt=0) | Q(opening_balance__gt=0),
        is_active=True,
    ).annotate(
        purchases=Sum('order__total'),
        remaining=Sum('order__remaining_amount'),
    ).order_by('-remaining')
    return {
        'title': 'Customer debt report',
        'summary': {'total_debt': qs.aggregate(v=Sum('remaining'))['v'] or ZERO},
        'rows': list(qs.values('name', 'phone', 'customer_type', 'opening_balance', 'credit_limit', 'purchases', 'remaining')[:200]),
    }


def inactive_customer_report(days=90):
    cutoff = timezone.now() - timedelta(days=days)
    qs = Customer.objects.filter(is_active=True).exclude(order__created_at__gte=cutoff).order_by('name')
    return {
        'title': 'Inactive customer report',
        'summary': {'days': days, 'customers': qs.count()},
        'rows': list(qs.values('name', 'phone', 'customer_type', 'created_at')[:200]),
    }


def discount_report(request):
    orders = apply_order_filters(Order.objects.filter(Q(discount__gt=0) | Q(discount_amount__gt=0)), request)
    return {
        'title': 'Discount report',
        'summary': {'orders': orders.count(), 'total_discounts': _sum(orders, 'discount')},
        'rows': list(orders.values(
            'order_number', 'created_at', 'customer__name', 'created_by__username',
            'subtotal', 'discount', 'discount_amount', 'discount_percentage', 'total', 'discount_reason',
        )[:300]),
    }


def sales_rep_custody_report(request):
    assignments = SalesRepStockAssignment.objects.select_related('sales_rep', 'product_variant__product', 'source_warehouse')
    if getattr(request.user, 'role', None) == 'sales' and not request.user.is_superuser:
        assignments = assignments.filter(sales_rep=request.user)
    return {
        'title': 'Sales rep custody report',
        'summary': {
            'assigned': _sum(assignments, 'quantity_assigned'),
            'sold': _sum(assignments, 'quantity_sold'),
            'returned': _sum(assignments, 'quantity_returned'),
            'remaining': _sum(assignments, 'quantity_remaining'),
        },
        'rows': list(assignments.values(
            'sales_rep__username', 'product_variant__product__name', 'source_warehouse__name',
            'quantity_assigned', 'quantity_sold', 'quantity_returned', 'quantity_remaining', 'is_active',
        )[:300]),
    }


def sales_rep_collections_report(request):
    collections = SalesRepCollection.objects.select_related('sales_rep', 'customer', 'order', 'cash_account')
    if getattr(request.user, 'role', None) == 'sales' and not request.user.is_superuser:
        collections = collections.filter(sales_rep=request.user)
    return {
        'title': 'Sales rep collections report',
        'summary': {
            'collected': _sum(collections, 'amount'),
            'handed_over': _sum(collections, 'handed_over_amount'),
        },
        'rows': list(collections.values(
            'collection_date', 'sales_rep__username', 'customer__name', 'order__order_number',
            'amount', 'handed_over_amount', 'handed_over', 'cash_account__name',
        )[:300]),
    }


def low_stock_report():
    qs = Stock.objects.select_related('warehouse', 'variant__product').filter(quantity__lte=F('min_quantity')).order_by('quantity')
    return {
        'title': 'Low stock report',
        'summary': {'items': qs.count()},
        'rows': list(qs.values('warehouse__name', 'variant__product__name', 'variant__variant_sku', 'quantity', 'min_quantity')[:300]),
    }


def stale_products_report(days=90):
    cutoff = timezone.now() - timedelta(days=days)
    sold_variant_ids = OrderItem.objects.filter(order__created_at__gte=cutoff).values('variant_id')
    qs = ProductVariant.objects.select_related('product').exclude(pk__in=sold_variant_ids).filter(is_active=True)
    return {
        'title': 'Stale products report',
        'summary': {'days': days, 'variants': qs.count()},
        'rows': list(qs.values('product__name', 'variant_sku', 'barcode', 'product__sku', 'product__retail_price', 'product__wholesale_price')[:300]),
    }


def returns_report(request):
    qs = SalesReturn.objects.select_related('order', 'customer', 'created_by')
    dates = date_range_from_request(request)
    if dates['parsed_from']:
        qs = qs.filter(created_at__date__gte=dates['parsed_from'])
    if dates['parsed_to']:
        qs = qs.filter(created_at__date__lte=dates['parsed_to'])
    return {
        'title': 'Returns report',
        'summary': {'returns': qs.count(), 'refund_amount': _sum(qs, 'refund_amount')},
        'rows': list(qs.values('created_at', 'order__order_number', 'customer__name', 'return_type', 'status', 'refund_amount', 'reason')[:300]),
        'sections': {
            'top_reasons': list(qs.values('reason').annotate(count=Count('id'), refund=Sum('refund_amount')).order_by('-count')[:20]),
            'top_products': list(SalesReturnItem.objects.filter(sales_return__in=qs).values(
                'product_variant__product__name',
            ).annotate(quantity=Sum('quantity'), refund=Sum('refund_amount')).order_by('-quantity')[:20]),
        },
    }


def purchase_report(request):
    qs = PurchaseOrder.objects.select_related('supplier').exclude(status=PurchaseOrder.STATUS_CANCELLED)
    dates = date_range_from_request(request)
    if dates['parsed_from']:
        qs = qs.filter(order_date__gte=dates['parsed_from'])
    if dates['parsed_to']:
        qs = qs.filter(order_date__lte=dates['parsed_to'])
    return {
        'title': 'Purchase report',
        'summary': {
            'orders': qs.count(),
            'total_amount': _sum(qs, 'total_amount'),
            'paid_amount': _sum(qs, 'paid_amount'),
            'remaining_amount': _sum(qs, 'remaining_amount'),
        },
        'rows': list(qs.values('purchase_number', 'order_date', 'supplier__name', 'status', 'total_amount', 'paid_amount', 'remaining_amount')[:300]),
    }


def supplier_dues_report():
    qs = Supplier.objects.filter(is_active=True, current_balance__gt=0).order_by('-current_balance')
    return {
        'title': 'Supplier dues report',
        'summary': {'suppliers': qs.count(), 'total_due': _sum(qs, 'current_balance')},
        'rows': list(qs.values('name', 'company_name', 'phone', 'opening_balance', 'current_balance')[:300]),
    }


def manager_dashboard_kpis():
    today = timezone.localdate()
    month_start = today.replace(day=1)
    valid_orders = Order.objects.exclude(status__in=EXCLUDED_SALES_STATUSES)
    today_orders = valid_orders.filter(created_at__date=today)
    month_orders = valid_orders.filter(created_at__date__gte=month_start)
    expenses = PaymentTransaction.objects.filter(transaction_type=PaymentTransaction.TYPE_EXPENSE)
    gross_profit = _sum(month_orders, 'gross_profit')
    expenses_total = _sum(expenses.filter(created_at__date__gte=month_start), 'amount')
    completed_returns = SalesReturn.objects.filter(status=SalesReturn.STATUS_COMPLETED)
    sold_qty = OrderItem.objects.filter(order__in=month_orders).aggregate(v=Sum('quantity'))['v'] or 0
    returned_qty = SalesReturnItem.objects.filter(sales_return__in=completed_returns).aggregate(v=Sum('quantity'))['v'] or 0
    return_rate = (Decimal(returned_qty) / Decimal(sold_qty) * 100) if sold_qty else ZERO
    return {
        'today_sales': _sum(today_orders, 'total'),
        'month_sales': _sum(month_orders, 'total'),
        'today_orders': today_orders.count(),
        'month_orders': month_orders.count(),
        'sales_cost_total': _sum(month_orders, 'total_cost'),
        'gross_profit': gross_profit,
        'expenses_total': expenses_total,
        'net_profit': gross_profit - expenses_total,
        'collections_total': _sum(PaymentTransaction.objects.filter(direction=PaymentTransaction.DIRECTION_IN), 'amount'),
        'customer_remaining_total': _sum(valid_orders, 'remaining_amount'),
        'supplier_dues_total': _sum(Supplier.objects.filter(is_active=True), 'current_balance'),
        'discount_total': _sum(month_orders, 'discount'),
        'returns_rate': round(return_rate, 2),
        'returns_count': completed_returns.count(),
        'today_collections': _sum(PaymentTransaction.objects.filter(direction=PaymentTransaction.DIRECTION_IN, created_at__date=today), 'amount'),
        'sales_rep_collections': _sum(SalesRepCollection.objects.filter(collection_date__gte=month_start), 'amount'),
        'cash_accounts': CashAccount.objects.filter(is_active=True).order_by('account_type', 'name'),
        'return_reasons': SalesReturn.objects.values('reason').annotate(count=Count('id')).order_by('-count')[:5],
        'employee_sales': valid_orders.values('created_by__username').annotate(total=Sum('total'), count=Count('id')).order_by('-total')[:10],
        'sales_rep_performance': SalesRepCollection.objects.values('sales_rep__username').annotate(total=Sum('amount'), count=Count('id')).order_by('-total')[:10],
        'purchase_period_total': _sum(PurchaseOrder.objects.filter(order_date__gte=month_start).exclude(status=PurchaseOrder.STATUS_CANCELLED), 'total_amount'),
        'top_products': OrderItem.objects.filter(order__in=month_orders).values('variant__product__name').annotate(qty=Sum('quantity')).order_by('-qty')[:10],
        'top_profit_products': OrderItem.objects.filter(order__in=month_orders).values('variant__product__name').annotate(profit=Sum('profit_total')).order_by('-profit')[:10],
        'low_profit_products': OrderItem.objects.filter(order__in=month_orders).values('variant__product__name').annotate(profit=Sum('profit_total')).order_by('profit')[:10],
        'low_stocks': Stock.objects.select_related('warehouse', 'variant__product').filter(quantity__lte=F('min_quantity'))[:10],
        'stale_products': stale_products_report()['rows'][:10],
        'latest_orders': Order.objects.select_related('customer', 'created_by').order_by('-created_at')[:10],
        'daily_sales_chart': valid_orders.filter(created_at__date__gte=today - timedelta(days=6)).annotate(day=TruncDate('created_at')).values('day').annotate(total=Sum('total')).order_by('day'),
    }
