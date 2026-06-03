from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from inventory.models import Stock, StockMovement
from inventory.services import return_stock, sale_stock

from .models import Order, OrderItem


def generate_order_number():
    today = timezone.localdate().strftime('%Y%m%d')
    count = Order.objects.filter(created_at__date=timezone.localdate()).count() + 1
    return f'ORD-{today}-{count:04d}'


def calculate_order_totals(order):
    subtotal = Decimal('0')
    discount = Decimal('0')
    for item in order.items.all():
        line_before_discount = item.unit_price * item.quantity
        subtotal += line_before_discount
        discount += item.discount
    total = max(subtotal - discount - order.discount, Decimal('0'))
    order.subtotal = subtotal
    order.total = total
    order.remaining_amount = max(total - order.paid_amount, Decimal('0'))
    if order.paid_amount <= 0:
        order.payment_status = Order.PAYMENT_UNPAID
    elif order.paid_amount >= total:
        order.payment_status = Order.PAYMENT_PAID
    else:
        order.payment_status = Order.PAYMENT_PARTIAL
    order.save(update_fields=['subtotal', 'total', 'remaining_amount', 'payment_status'])
    return order


@transaction.atomic
def create_order(*, order_data, items, user, confirm=False):
    order = Order.objects.create(
        order_number=generate_order_number(),
        created_by=user,
        **order_data,
    )
    for item in items:
        variant = item['variant']
        quantity = int(item['quantity'])
        unit_price = Decimal(str(item['unit_price']))
        discount = Decimal(str(item.get('discount', 0)))
        OrderItem.objects.create(
            order=order,
            variant=variant,
            quantity=quantity,
            unit_price=unit_price,
            discount=discount,
            total=max((unit_price * quantity) - discount, Decimal('0')),
        )
    calculate_order_totals(order)
    if confirm:
        order = confirm_order(order=order, user=user)
    return order


@transaction.atomic
def confirm_order(*, order, user):
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.status != Order.STATUS_DRAFT:
        raise ValidationError('يمكن تأكيد الطلبات المسودة فقط')
    if not order.items.exists():
        raise ValidationError('لا يمكن تأكيد طلب بدون منتجات')
    for item in order.items.select_related('variant'):
        stock = Stock.objects.select_for_update().filter(warehouse=order.warehouse, variant=item.variant).first()
        if not stock or stock.quantity < item.quantity:
            raise ValidationError(f'الكمية غير متاحة: {item.variant}')
    for item in order.items.select_related('variant'):
        sale_stock(
            variant=item.variant,
            warehouse=order.warehouse,
            quantity=item.quantity,
            user=user,
            note=f'بيع من الطلب {order.order_number}',
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
    for item in order.items.select_related('variant'):
        return_stock(
            variant=item.variant,
            warehouse=order.warehouse,
            quantity=item.quantity,
            user=user,
            note=f'إلغاء الطلب {order.order_number}',
        )
    order.status = Order.STATUS_CANCELLED
    order.save(update_fields=['status'])
    return order


@transaction.atomic
def return_order(*, order, user):
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.status not in {Order.STATUS_CONFIRMED, Order.STATUS_PREPARING, Order.STATUS_READY, Order.STATUS_COMPLETED}:
        raise ValidationError('لا يمكن عمل مرتجع لهذا الطلب')
    for item in order.items.select_related('variant'):
        return_stock(
            variant=item.variant,
            warehouse=order.warehouse,
            quantity=item.quantity,
            user=user,
            note=f'مرتجع الطلب {order.order_number}',
        )
    order.status = Order.STATUS_RETURNED
    order.save(update_fields=['status'])
    return order
