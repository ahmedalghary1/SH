from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from customers.models import Customer
from inventory.models import Stock, StockMovement
from inventory.services import return_stock, sale_stock
from settings_app.models import CompanySettings

from .models import Order, OrderItem


def _as_decimal(value):
    return Decimal(str(value or 0))


def generate_order_number():
    today = timezone.localdate().strftime('%Y%m%d')
    count = Order.objects.filter(created_at__date=timezone.localdate()).count() + 1
    return f'ORD-{today}-{count:04d}'


def get_price_for_customer(variant, customer=None, order_type=None):
    return getattr(variant, 'sale_price', None) or Decimal('0')


def get_discount_limits(user, customer=None):
    settings = CompanySettings.load()
    if getattr(user, 'is_manager', False) or getattr(user, 'is_superuser', False):
        return Decimal('100'), settings.allow_manager_sell_below_cost
    if getattr(customer, 'customer_type', '') == Customer.TYPE_VIP:
        return Decimal(str(settings.max_vip_discount_percentage)), False
    if getattr(user, 'role', None) == User.ROLE_SALES:
        return Decimal(str(settings.max_sales_discount_percentage)), False
    return Decimal('0'), False


def calculate_discount_amount(*, base_amount, discount_amount=0, discount_percentage=0):
    base_amount = _as_decimal(base_amount)
    discount_amount = _as_decimal(discount_amount)
    discount_percentage = _as_decimal(discount_percentage)
    if discount_amount < 0:
        raise ValidationError('قيمة الخصم لا يمكن أن تكون سالبة')
    if discount_percentage < 0 or discount_percentage > 100:
        raise ValidationError('نسبة الخصم يجب أن تكون بين 0 و 100')
    calculated = discount_amount + (base_amount * discount_percentage / Decimal('100'))
    return min(calculated, base_amount)


def _validate_discount_percentage(*, discount_amount, discount_percentage, base_amount, max_percentage):
    base_amount = _as_decimal(base_amount)
    if base_amount <= 0:
        return
    total_discount = calculate_discount_amount(
        base_amount=base_amount,
        discount_amount=discount_amount,
        discount_percentage=discount_percentage,
    )
    effective_percentage = (total_discount / base_amount) * Decimal('100')
    if effective_percentage > max_percentage:
        raise ValidationError('الخصم أكبر من الحد المسموح لهذا المستخدم')


def prepare_order_item_pricing(*, variant, quantity, user, customer=None, order_type=None, unit_price=None, discount_amount=0, discount_percentage=0, unit_cost=None, allow_free=False):
    quantity = int(quantity)
    if quantity <= 0:
        raise ValidationError('الكمية يجب أن تكون أكبر من صفر')
    default_price = _as_decimal(get_price_for_customer(variant, customer=customer, order_type=order_type))
    original_unit_price = default_price if unit_price in (None, '') else _as_decimal(unit_price)
    if original_unit_price < 0:
        raise ValidationError('سعر البيع لا يمكن أن يكون سالبا')
    line_base = original_unit_price * quantity
    max_discount, can_sell_below_cost = get_discount_limits(user, customer=customer)
    _validate_discount_percentage(
        discount_amount=discount_amount,
        discount_percentage=discount_percentage,
        base_amount=line_base,
        max_percentage=max_discount,
    )
    line_discount = calculate_discount_amount(
        base_amount=line_base,
        discount_amount=discount_amount,
        discount_percentage=discount_percentage,
    )
    line_total = max(line_base - line_discount, Decimal('0'))
    final_unit_price = line_total / quantity
    unit_cost = _as_decimal(unit_cost if unit_cost is not None else getattr(variant, 'cost_price', 0) or 0)
    if final_unit_price < unit_cost and not (can_sell_below_cost or allow_free):
        raise ValidationError('لا يمكن البيع تحت التكلفة لهذا المستخدم')
    cost_total = unit_cost * quantity
    return {
        'original_unit_price': original_unit_price,
        'discount_amount': _as_decimal(discount_amount),
        'discount_percentage': _as_decimal(discount_percentage),
        'line_discount': line_discount,
        'final_unit_price': final_unit_price,
        'unit_cost': unit_cost,
        'total': line_total,
        'cost_total': cost_total,
        'profit_total': line_total - cost_total,
    }


def calculate_order_totals(order):
    subtotal = Decimal('0')
    item_discounts = Decimal('0')
    total_cost = Decimal('0')
    for item in order.items.all():
        base_price = item.original_unit_price or item.unit_price
        line_before_discount = base_price * item.quantity
        line_discount = calculate_discount_amount(
            base_amount=line_before_discount,
            discount_amount=item.discount_amount or item.discount,
            discount_percentage=item.discount_percentage,
        )
        item.final_unit_price = max((line_before_discount - line_discount) / item.quantity, Decimal('0'))
        item.unit_price = item.final_unit_price
        item.discount = line_discount
        item.total = max(line_before_discount - line_discount, Decimal('0'))
        item.cost_total = item.unit_cost * item.quantity
        item.profit_total = item.total - item.cost_total
        item.save(update_fields=['unit_price', 'discount', 'final_unit_price', 'total', 'cost_total', 'profit_total'])
        subtotal += line_before_discount
        item_discounts += line_discount
        total_cost += item.cost_total
    order_discount = calculate_discount_amount(
        base_amount=max(subtotal - item_discounts, Decimal('0')),
        discount_amount=order.discount_amount or order.discount,
        discount_percentage=order.discount_percentage,
    )
    order.discount_amount = order_discount
    order.discount = order_discount
    total = max(subtotal - item_discounts - order_discount, Decimal('0'))
    order.subtotal = subtotal
    order.total = total
    order.total_cost = total_cost
    order.gross_profit = total - total_cost
    order.remaining_amount = max(total - order.paid_amount, Decimal('0'))
    if order.paid_amount <= 0:
        order.payment_status = Order.PAYMENT_UNPAID
    elif order.paid_amount >= total:
        order.payment_status = Order.PAYMENT_PAID
    else:
        order.payment_status = Order.PAYMENT_PARTIAL
    order.save(update_fields=[
        'subtotal', 'discount', 'discount_amount', 'total', 'total_cost',
        'gross_profit', 'remaining_amount', 'payment_status',
    ])
    return order


def get_order_item_warehouse(item, order=None):
    warehouse = getattr(item, 'warehouse', None) or getattr(order or item.order, 'warehouse', None)
    if not warehouse:
        raise ValidationError('يجب تحديد مخزن لكل صنف في الفاتورة')
    return warehouse


@transaction.atomic
def create_order(*, order_data, items, user, confirm=False):
    order_data = dict(order_data)
    document_type = order_data.get('document_type') or Order.DOCUMENT_SALE
    if document_type == Order.DOCUMENT_QUOTE:
        confirm = False
    customer = order_data.get('customer')
    if not order_data.get('warehouse') and items:
        order_data['warehouse'] = items[0].get('warehouse')
    order_discount_amount = Decimal('0') if document_type == Order.DOCUMENT_SAMPLE else _as_decimal(order_data.get('discount_amount', order_data.get('discount', 0)))
    order_discount_percentage = Decimal('0') if document_type == Order.DOCUMENT_SAMPLE else _as_decimal(order_data.get('discount_percentage', 0))
    order_data['discount_amount'] = order_discount_amount
    order_data['discount_percentage'] = order_discount_percentage
    order_data['discount'] = order_discount_amount
    if order_discount_amount > 0 or order_discount_percentage > 0:
        order_data['discount_approved_by'] = user
    order = Order.objects.create(
        order_number=generate_order_number(),
        created_by=user,
        **order_data,
    )
    subtotal_after_item_discounts = Decimal('0')
    subtotal_before_item_discounts = Decimal('0')
    item_discount_total = Decimal('0')
    max_discount, _ = get_discount_limits(user, customer=customer)
    for item in items:
        variant = item['variant']
        warehouse = item.get('warehouse') or order.warehouse
        stock_batch = item.get('stock_batch')
        if not warehouse:
            raise ValidationError('يجب تحديد مخزن لكل صنف في الفاتورة')
        quantity = int(item['quantity'])
        is_sample = document_type == Order.DOCUMENT_SAMPLE
        pricing = prepare_order_item_pricing(
            variant=variant,
            quantity=quantity,
            user=user,
            customer=customer,
            order_type=order.order_type,
            unit_price=0 if is_sample else item.get('unit_price'),
            discount_amount=0 if is_sample else item.get('discount_amount', item.get('discount', 0)),
            discount_percentage=0 if is_sample else item.get('discount_percentage', 0),
            unit_cost=getattr(stock_batch, 'unit_cost', None),
            allow_free=is_sample,
        )
        subtotal_before_item_discounts += pricing['original_unit_price'] * quantity
        item_discount_total += pricing['line_discount']
        subtotal_after_item_discounts += pricing['total']
        OrderItem.objects.create(
            order=order,
            variant=variant,
            warehouse=warehouse,
            stock_batch=stock_batch,
            quantity=quantity,
            unit_price=pricing['final_unit_price'],
            original_unit_price=pricing['original_unit_price'],
            discount_amount=pricing['discount_amount'],
            discount_percentage=pricing['discount_percentage'],
            final_unit_price=pricing['final_unit_price'],
            unit_cost=pricing['unit_cost'],
            discount=pricing['line_discount'],
            total=pricing['total'],
            cost_total=pricing['cost_total'],
            profit_total=pricing['profit_total'],
        )
    _validate_discount_percentage(
        discount_amount=order_discount_amount,
        discount_percentage=order_discount_percentage,
        base_amount=subtotal_after_item_discounts,
        max_percentage=max_discount,
    )
    order_discount_total = calculate_discount_amount(
        base_amount=subtotal_after_item_discounts,
        discount_amount=order_discount_amount,
        discount_percentage=order_discount_percentage,
    )
    _validate_discount_percentage(
        discount_amount=item_discount_total + order_discount_total,
        discount_percentage=0,
        base_amount=subtotal_before_item_discounts,
        max_percentage=max_discount,
    )
    calculate_order_totals(order)
    if document_type == Order.DOCUMENT_SALE and order.total > 0 and order.payment_method != Order.METHOD_CREDIT:
        from finance.services import record_order_sale_payment

        record_order_sale_payment(
            order=order,
            user=user,
            notes=f'قيمة بيع تلقائية للطلب {order.order_number}',
        )
        order.refresh_from_db()
    elif document_type == Order.DOCUMENT_SAMPLE:
        order.paid_amount = Decimal('0')
        order.remaining_amount = Decimal('0')
        order.payment_status = Order.PAYMENT_PAID
        order.save(update_fields=['paid_amount', 'remaining_amount', 'payment_status'])
    if confirm:
        order = confirm_order(order=order, user=user)
    return order


@transaction.atomic
def confirm_order(*, order, user):
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.document_type == Order.DOCUMENT_QUOTE:
        raise ValidationError('هذه فاتورة مسعرة فقط ولا تخصم من المخزون')
    if order.status != Order.STATUS_DRAFT:
        raise ValidationError('يمكن تأكيد الطلبات المسودة فقط')
    if not order.items.exists():
        raise ValidationError('لا يمكن تأكيد طلب بدون منتجات')
    for item in order.items.select_related('variant', 'warehouse', 'stock_batch'):
        warehouse = get_order_item_warehouse(item, order=order)
        stock = Stock.objects.select_for_update().filter(warehouse=warehouse, variant=item.variant).first()
        if not stock or stock.quantity < item.quantity:
            raise ValidationError(f'الكمية غير متاحة: {item.variant}')
        if item.stock_batch and item.stock_batch.remaining_quantity < item.quantity:
            raise ValidationError(f'الكمية غير متاحة في دفعة السعر: {item.variant}')
    movement_type = StockMovement.TYPE_SAMPLE if order.document_type == Order.DOCUMENT_SAMPLE else StockMovement.TYPE_SALE
    for item in order.items.select_related('variant', 'warehouse', 'stock_batch'):
        warehouse = get_order_item_warehouse(item, order=order)
        sale_stock(
            variant=item.variant,
            warehouse=warehouse,
            quantity=item.quantity,
            user=user,
            batch=item.stock_batch,
            movement_type=movement_type,
            note=f'صرف من الطلب {order.order_number}',
        )
    if (
        order.document_type == Order.DOCUMENT_SALE
        and order.total > 0
        and order.paid_amount <= 0
        and order.payment_method != Order.METHOD_CREDIT
    ):
        from finance.services import record_order_sale_payment

        order.paid_amount = order.total
        order.remaining_amount = Decimal('0')
        order.payment_status = Order.PAYMENT_PAID
        order.save(update_fields=['paid_amount', 'remaining_amount', 'payment_status'])
        record_order_sale_payment(
            order=order,
            user=user,
            notes=f'قيمة بيع تلقائية للطلب {order.order_number}',
        )
    order.status = Order.STATUS_CONFIRMED
    order.save(update_fields=['status'])
    return order


@transaction.atomic
def cancel_order(*, order, user):
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.status == Order.STATUS_DRAFT:
        order.status = Order.STATUS_CANCELLED
        order.save(update_fields=['status'])
        return order
    if order.status not in {Order.STATUS_CONFIRMED, Order.STATUS_PREPARING, Order.STATUS_READY, Order.STATUS_COMPLETED}:
        raise ValidationError('لا يمكن إلغاء هذا الطلب')
    for item in order.items.select_related('variant', 'warehouse'):
        warehouse = get_order_item_warehouse(item, order=order)
        return_stock(
            variant=item.variant,
            warehouse=warehouse,
            quantity=item.quantity,
            user=user,
            unit_cost=item.unit_cost,
            note=f'إلغاء الطلب {order.order_number}',
        )
    if order.document_type == Order.DOCUMENT_SALE and order.total > 0:
        from finance.services import record_order_refund

        record_order_refund(order=order, user=user, notes=f'رد تلقائي لإلغاء الطلب {order.order_number}')
    order.status = Order.STATUS_CANCELLED
    order.save(update_fields=['status'])
    return order


@transaction.atomic
def return_order(*, order, user):
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.status not in {Order.STATUS_CONFIRMED, Order.STATUS_PREPARING, Order.STATUS_READY, Order.STATUS_COMPLETED}:
        raise ValidationError('لا يمكن عمل مرتجع لهذا الطلب')
    for item in order.items.select_related('variant', 'warehouse'):
        warehouse = get_order_item_warehouse(item, order=order)
        return_stock(
            variant=item.variant,
            warehouse=warehouse,
            quantity=item.quantity,
            user=user,
            unit_cost=item.unit_cost,
            note=f'مرتجع الطلب {order.order_number}',
        )
    order.status = Order.STATUS_RETURNED
    order.save(update_fields=['status'])
    return order
