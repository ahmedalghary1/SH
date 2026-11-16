"""Net economics of a selected cohort of invoices, after completed returns."""
from collections import defaultdict
from decimal import Decimal

from returns.models import SalesReturn

ZERO = Decimal('0')
CENT = Decimal('0.01')


def net_invoice_financials(orders):
    orders = list(orders.select_related('customer', 'created_by').prefetch_related('items__variant__product__category'))
    by_order = {order.pk: {'order': order, 'total': order.total, 'cost': order.total_cost} for order in orders}
    product_rows = {}
    item_rows = {}

    def product_row(variant):
        product = variant.product if variant else None
        key = product.pk if product else None
        return product_rows.setdefault(key, {'product': product.name if product else 'صنف محذوف',
            'category': str(product.category or '-') if product else '-', 'total': ZERO, 'cost': ZERO})

    for order in orders:
        lines = list(order.items.all())
        base = sum((line.total for line in lines), ZERO)
        preceding = ZERO
        for line in lines:
            after = preceding + line.total
            net = ((order.total * after / base).quantize(CENT)
                   - (order.total * preceding / base).quantize(CENT)) if base else ZERO
            preceding = after
            row = product_row(line.variant)
            row['total'] += net
            row['cost'] += line.cost_total
            item_rows[line.pk] = (line, row)

    returns = SalesReturn.objects.filter(order_id__in=by_order, status=SalesReturn.STATUS_COMPLETED).prefetch_related(
        'items__original_order_item', 'exchange_items__new_product_variant__product__category')
    good_quantities = defaultdict(int)
    refunds = ZERO
    exchange_delta = ZERO
    estimated = 0
    for result in returns:
        values = by_order[result.order_id]
        returned_values = defaultdict(lambda: ZERO)
        for line in result.items.all():
            returned_values[line.original_order_item_id] += line.refund_amount
            original, product = item_rows[line.original_order_item_id]
            # Replacements carry the exchanged product's sales value.
            product['total'] -= line.refund_amount
            if line.condition == 'good' and line.return_to_stock:
                good_quantities[original.pk] += line.quantity
        if result.return_type != SalesReturn.TYPE_EXCHANGE:
            values['total'] -= result.refund_amount
            refunds += result.refund_amount
            continue
        exchanged = list(result.exchange_items.all())
        counts = defaultdict(int)
        for line in exchanged:
            counts[line.old_order_item_id] += line.quantity
        allocated = defaultdict(lambda: ZERO)
        seen = defaultdict(int)
        for line in exchanged:
            seen[line.old_order_item_id] += line.quantity
            target = (returned_values[line.old_order_item_id] * seen[line.old_order_item_id]
                      / counts[line.old_order_item_id]).quantize(CENT)
            old_value = target - allocated[line.old_order_item_id]
            allocated[line.old_order_item_id] = target
            cost = line.cost_total
            if cost is None:
                cost = line.new_product_variant.cost_price * line.quantity
                estimated += 1
            row = product_row(line.new_product_variant)
            row['total'] += old_value + line.price_difference
            row['cost'] += cost
            values['total'] += line.price_difference
            values['cost'] += cost
            exchange_delta += line.price_difference
    for item_id, quantity in good_quantities.items():
        line, row = item_rows[item_id]
        cost = (line.cost_total * quantity / line.quantity).quantize(CENT)
        row['cost'] -= cost
        by_order[line.order_id]['cost'] -= cost
    for row in [*by_order.values(), *product_rows.values()]:
        row['profit'] = row['total'] - row['cost']
    return {'total_sales': sum((row['total'] for row in by_order.values()), ZERO),
        'total_cost': sum((row['cost'] for row in by_order.values()), ZERO),
        'gross_profit': sum((row['profit'] for row in by_order.values()), ZERO),
        'gross_sales': sum((order.total for order in orders), ZERO), 'returns_total': refunds,
        'exchange_difference': exchange_delta, 'estimated_exchange_lines': estimated,
        'orders': list(by_order.values()), 'products': list(product_rows.values())}


def financial_sections(financials):
    categories, employees, customers = {}, {}, {}
    products = []
    for row in financials['products']:
        products.append({'variant__product__name': row['product'], 'total': row['total'],
                         'cost': row['cost'], 'profit': row['profit']})
        group = categories.setdefault(row['category'], {'variant__product__category__name': row['category'],
            'total': ZERO, 'cost': ZERO, 'profit': ZERO})
        for field in ('total', 'cost', 'profit'):
            group[field] += row[field]
    for row in financials['orders']:
        order = row['order']
        employee = employees.setdefault(order.created_by_id, {'created_by__username': str(order.created_by or '-'),
            'total': ZERO, 'cost': ZERO, 'profit': ZERO, 'orders': 0})
        customer = customers.setdefault(order.customer_id, {'customer__name': order.customer.name if order.customer else '-',
            'customer__phone': order.customer.phone if order.customer else '',
            'total': ZERO, 'cost': ZERO, 'profit': ZERO, 'orders': 0})
        for group in (employee, customer):
            for field in ('total', 'cost', 'profit'):
                group[field] += row[field]
            group['orders'] += 1
    top = lambda rows: sorted(rows, key=lambda row: row['profit'], reverse=True)[:50]
    return {'profit_by_product': top(products), 'profit_by_category': top(categories.values()),
            'profit_by_employee': top(employees.values()), 'profit_by_customer': top(customers.values())}


def financial_periods(financials, period):
    from django.utils import timezone
    groups = {}
    for row in financials['orders']:
        order = row['order']
        day = timezone.localtime(order.created_at).date()
        key = day.replace(day=1) if period == 'month' else day.year
        group = groups.setdefault(key, {period: key, 'total': ZERO, 'cost': ZERO, 'profit': ZERO,
                                       'paid': ZERO, 'remaining': ZERO, 'count': 0})
        for field in ('total', 'cost', 'profit'):
            group[field] += row[field]
        group['paid'] += order.paid_amount
        group['remaining'] += order.remaining_amount
        group['count'] += 1
    return sorted(groups.values(), key=lambda row: row[period], reverse=True)
