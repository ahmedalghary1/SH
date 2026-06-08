from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Sum

from audit.models import AuditLog
from audit.services import log_audit
from finance.models import PaymentTransaction
from finance.services import record_transaction
from inventory.models import Stock, StockMovement
from orders.models import Order
from orders.services import get_order_item_warehouse

from .models import ExchangeItem, SalesReturn, SalesReturnItem


def _line_refund_unit_price(order_item):
    if order_item.quantity <= 0:
        return Decimal('0')
    return (order_item.total / Decimal(order_item.quantity)).quantize(Decimal('0.01'))


def calculate_available_return_quantity(order_item):
    returned = SalesReturnItem.objects.filter(
        original_order_item=order_item,
        sales_return__status=SalesReturn.STATUS_COMPLETED,
    ).aggregate(v=Sum('quantity'))['v'] or 0
    return max(order_item.quantity - returned, 0)


@transaction.atomic
def create_sales_return(*, order, return_type, reason='', user):
    if order.status in {Order.STATUS_DRAFT, Order.STATUS_CANCELLED, Order.STATUS_RETURNED}:
        raise ValidationError('لا يمكن إنشاء مرتجع لهذا الطلب في حالته الحالية')
    sales_return = SalesReturn.objects.create(
        order=order,
        customer=order.customer,
        return_type=return_type,
        reason=reason,
        created_by=user,
    )
    
    log_audit(
        user=user,
        action=AuditLog.ACTION_CREATE,
        section=AuditLog.SECTION_RETURNS,
        model_name='SalesReturn',
        object_id=sales_return.pk,
        object_repr=str(sales_return),
        changes_before={},
        changes_after={'order': str(order), 'return_type': return_type},
        notes=f'إنشاء مرتجع للطلب {order.order_number} - النوع: {return_type}',
    )
    
    return sales_return


@transaction.atomic
def add_return_item(*, sales_return, original_order_item, quantity, condition=SalesReturnItem.CONDITION_GOOD, return_to_stock=True, notes=''):
    sales_return = SalesReturn.objects.select_for_update().get(pk=sales_return.pk)
    if sales_return.status != SalesReturn.STATUS_DRAFT:
        raise ValidationError('يمكن تعديل المرتجع في حالة المسودة فقط')
    if original_order_item.order_id != sales_return.order_id:
        raise ValidationError('الصنف لا يتبع الطلب المرتبط بالمرتجع')
    quantity = int(quantity)
    if quantity <= 0:
        raise ValidationError('كمية المرتجع يجب أن تكون أكبر من صفر')
    available = calculate_available_return_quantity(original_order_item)
    if quantity > available:
        raise ValidationError('كمية المرتجع أكبر من الكمية المتاحة للإرجاع')
    if not original_order_item.variant:
        raise ValidationError('لا يمكن إرجاع صنف بدون متغير منتج')

    refund_amount = _line_refund_unit_price(original_order_item) * quantity
    item = SalesReturnItem.objects.create(
        sales_return=sales_return,
        original_order_item=original_order_item,
        product_variant=original_order_item.variant,
        quantity=quantity,
        condition=condition,
        return_to_stock=return_to_stock,
        refund_amount=refund_amount,
        notes=notes,
    )
    _recalculate_refund_amount(sales_return)
    
    log_audit(
        user=sales_return.created_by,
        action=AuditLog.ACTION_CREATE,
        section=AuditLog.SECTION_RETURNS,
        model_name='SalesReturnItem',
        object_id=item.pk,
        object_repr=str(item),
        changes_before={},
        changes_after={'quantity': quantity, 'refund_amount': str(refund_amount)},
        notes=f'إضافة صنف مرتجع: {original_order_item.variant} - الكمية: {quantity}',
    )
    
    return item


@transaction.atomic
def add_exchange_item(*, sales_return, old_order_item, new_product_variant, quantity, new_unit_price, notes=''):
    sales_return = SalesReturn.objects.select_for_update().get(pk=sales_return.pk)
    if sales_return.status != SalesReturn.STATUS_DRAFT:
        raise ValidationError('يمكن تعديل الاستبدال في حالة المسودة فقط')
    if sales_return.return_type != SalesReturn.TYPE_EXCHANGE:
        raise ValidationError('إضافة صنف استبدال متاحة لمرتجع الاستبدال فقط')
    if old_order_item.order_id != sales_return.order_id:
        raise ValidationError('الصنف القديم لا يتبع الطلب المرتبط بالمرتجع')
    quantity = int(quantity)
    if quantity <= 0:
        raise ValidationError('كمية الاستبدال يجب أن تكون أكبر من صفر')
    if quantity > calculate_available_return_quantity(old_order_item):
        raise ValidationError('كمية الاستبدال أكبر من الكمية المتاحة للإرجاع')

    old_unit_price = _line_refund_unit_price(old_order_item)
    new_unit_price = Decimal(str(new_unit_price))
    price_difference = (new_unit_price - old_unit_price) * quantity
    item = ExchangeItem.objects.create(
        sales_return=sales_return,
        old_order_item=old_order_item,
        new_product_variant=new_product_variant,
        quantity=quantity,
        new_unit_price=new_unit_price,
        old_unit_price=old_unit_price,
        price_difference=price_difference,
        notes=notes,
    )
    
    log_audit(
        user=sales_return.created_by,
        action=AuditLog.ACTION_CREATE,
        section=AuditLog.SECTION_RETURNS,
        model_name='ExchangeItem',
        object_id=item.pk,
        object_repr=str(item),
        changes_before={},
        changes_after={
            'old_variant': str(old_order_item.variant),
            'new_variant': str(new_product_variant),
            'quantity': quantity,
            'price_difference': str(price_difference),
        },
        notes=f'إضافة صنف استبدال: {old_order_item.variant} إلى {new_product_variant}',
    )
    
    return item


@transaction.atomic
def approve_sales_return(*, sales_return, user):
    sales_return = SalesReturn.objects.select_for_update().get(pk=sales_return.pk)
    old_status = sales_return.status
    if sales_return.status != SalesReturn.STATUS_DRAFT:
        raise ValidationError('يمكن اعتماد المرتجع من حالة المسودة فقط')
    if not sales_return.items.exists():
        raise ValidationError('لا يمكن اعتماد مرتجع بدون أصناف')
    sales_return.status = SalesReturn.STATUS_APPROVED
    sales_return.approved_by = user
    sales_return.save(update_fields=['status', 'approved_by'])
    
    log_audit(
        user=user,
        action=AuditLog.ACTION_CONFIRM,
        section=AuditLog.SECTION_RETURNS,
        model_name='SalesReturn',
        object_id=sales_return.pk,
        object_repr=str(sales_return),
        changes_before={'status': old_status},
        changes_after={'status': sales_return.status},
        notes=f'اعتماد مرتجع للطلب {sales_return.order.order_number}',
    )
    
    return sales_return


@transaction.atomic
def complete_sales_return(*, sales_return, user, cash_account=None):
    sales_return = SalesReturn.objects.select_for_update().select_related('order', 'customer').get(pk=sales_return.pk)
    old_status = sales_return.status
    if sales_return.status != SalesReturn.STATUS_APPROVED:
        raise ValidationError('يجب اعتماد المرتجع قبل إكماله')

    order = Order.objects.select_for_update().get(pk=sales_return.order_id)
    for item in sales_return.items.select_related('product_variant', 'original_order_item__warehouse'):
        item_warehouse = get_order_item_warehouse(item.original_order_item, order=order)
        if item.condition == SalesReturnItem.CONDITION_GOOD and item.return_to_stock:
            _increase_stock_for_return(order=order, item=item, user=user)
        elif item.condition == SalesReturnItem.CONDITION_DAMAGED:
            StockMovement.objects.create(
                movement_type=StockMovement.TYPE_DAMAGED_RETURN,
                variant=item.product_variant,
                to_warehouse=item_warehouse,
                quantity=item.quantity,
                note=f'Damaged return for order {order.order_number}',
                created_by=user,
            )

    _process_exchange_stock_and_money(sales_return=sales_return, order=order, user=user, cash_account=cash_account)
    _process_refund(sales_return=sales_return, order=order, user=user, cash_account=cash_account)

    sales_return.status = SalesReturn.STATUS_COMPLETED
    sales_return.completed_by = user
    sales_return.save(update_fields=['status', 'completed_by'])
    _update_order_return_status(order)
    
    log_audit(
        user=user,
        action=AuditLog.ACTION_RETURN,
        section=AuditLog.SECTION_RETURNS,
        model_name='SalesReturn',
        object_id=sales_return.pk,
        object_repr=str(sales_return),
        changes_before={'status': old_status},
        changes_after={'status': sales_return.status},
        notes=f'إكمال مرتجع للطلب {order.order_number} - المبلغ: {sales_return.refund_amount}',
    )
    
    return sales_return


def process_refund(*, sales_return, user, cash_account=None):
    return complete_sales_return(sales_return=sales_return, user=user, cash_account=cash_account)


def process_exchange(*, sales_return, user, cash_account=None):
    return complete_sales_return(sales_return=sales_return, user=user, cash_account=cash_account)


def _increase_stock_for_return(*, order, item, user):
    warehouse = get_order_item_warehouse(item.original_order_item, order=order)
    stock, _ = Stock.objects.select_for_update().get_or_create(
        warehouse=warehouse,
        variant=item.product_variant,
        defaults={'quantity': 0},
    )
    stock.quantity = F('quantity') + item.quantity
    stock.save(update_fields=['quantity'])
    StockMovement.objects.create(
        movement_type=StockMovement.TYPE_SALES_RETURN,
        variant=item.product_variant,
        to_warehouse=warehouse,
        quantity=item.quantity,
        note=f'Sales return for order {order.order_number}',
        created_by=user,
    )


def _process_refund(*, sales_return, order, user, cash_account):
    if sales_return.return_type == SalesReturn.TYPE_EXCHANGE:
        return None
    refund_amount = sales_return.items.aggregate(v=Sum('refund_amount'))['v'] or Decimal('0')
    if refund_amount <= 0:
        return None
    return record_transaction(
        transaction_type=PaymentTransaction.TYPE_REFUND,
        direction=PaymentTransaction.DIRECTION_OUT,
        amount=refund_amount,
        cash_account=cash_account,
        related_order=order,
        related_customer=sales_return.customer,
        notes=f'Refund for return {sales_return.pk} / order {order.order_number}',
        created_by=user,
    )


def _process_exchange_stock_and_money(*, sales_return, order, user, cash_account):
    for exchange in sales_return.exchange_items.select_related('new_product_variant', 'old_order_item__warehouse'):
        warehouse = get_order_item_warehouse(exchange.old_order_item, order=order)
        stock = Stock.objects.select_for_update().filter(
            warehouse=warehouse,
            variant=exchange.new_product_variant,
        ).first()
        if not stock or stock.quantity < exchange.quantity:
            raise ValidationError('مخزون صنف الاستبدال غير كاف')
        stock.quantity = F('quantity') - exchange.quantity
        stock.save(update_fields=['quantity'])
        StockMovement.objects.create(
            movement_type=StockMovement.TYPE_EXCHANGE_OUT,
            variant=exchange.new_product_variant,
            from_warehouse=warehouse,
            quantity=exchange.quantity,
            note=f'Exchange out for order {order.order_number}',
            created_by=user,
        )
        if exchange.price_difference > 0:
            record_transaction(
                transaction_type=PaymentTransaction.TYPE_CUSTOMER_PAYMENT,
                direction=PaymentTransaction.DIRECTION_IN,
                amount=exchange.price_difference,
                cash_account=cash_account,
                related_order=order,
                related_customer=sales_return.customer,
                notes=f'Exchange price difference for return {sales_return.pk}',
                created_by=user,
            )
        elif exchange.price_difference < 0:
            record_transaction(
                transaction_type=PaymentTransaction.TYPE_REFUND,
                direction=PaymentTransaction.DIRECTION_OUT,
                amount=abs(exchange.price_difference),
                cash_account=cash_account,
                related_order=order,
                related_customer=sales_return.customer,
                notes=f'Exchange refund difference for return {sales_return.pk}',
                created_by=user,
            )


def _recalculate_refund_amount(sales_return):
    total = sales_return.items.aggregate(v=Sum('refund_amount'))['v'] or Decimal('0')
    sales_return.refund_amount = total
    sales_return.save(update_fields=['refund_amount'])
    return total


def _update_order_return_status(order):
    total_quantity = order.items.aggregate(v=Sum('quantity'))['v'] or 0
    returned_quantity = SalesReturnItem.objects.filter(
        original_order_item__order=order,
        sales_return__status=SalesReturn.STATUS_COMPLETED,
    ).aggregate(v=Sum('quantity'))['v'] or 0
    if returned_quantity >= total_quantity and total_quantity > 0:
        order.status = Order.STATUS_RETURNED
    elif returned_quantity > 0:
        order.status = Order.STATUS_PARTIALLY_RETURNED
    order.save(update_fields=['status'])
