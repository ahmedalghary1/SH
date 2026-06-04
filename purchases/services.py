from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from finance.models import PaymentTransaction
from finance.services import record_transaction
from inventory.models import Stock, StockMovement

from .models import PurchaseOrder, PurchaseOrderItem, Supplier


def generate_purchase_number():
    today = timezone.localdate().strftime('%Y%m%d')
    count = PurchaseOrder.objects.filter(created_at__date=timezone.localdate()).count() + 1
    return f'PO-{today}-{count:04d}'


def recalculate_purchase_order(purchase_order):
    total = Decimal('0')
    for item in purchase_order.items.all():
        item.total_cost = item.unit_cost * item.quantity
        item.save(update_fields=['total_cost'])
        total += item.total_cost
    purchase_order.total_amount = total
    purchase_order.remaining_amount = max(total - purchase_order.paid_amount, Decimal('0'))
    purchase_order.save(update_fields=['total_amount', 'remaining_amount'])
    return purchase_order


@transaction.atomic
def create_purchase_order(*, supplier, items, user, status=PurchaseOrder.STATUS_ORDERED, order_date=None, expected_date=None, notes=''):
    if status not in {PurchaseOrder.STATUS_DRAFT, PurchaseOrder.STATUS_ORDERED}:
        raise ValidationError('حالة أمر الشراء عند الإنشاء يجب أن تكون مسودة أو تم الطلب')
    if not items:
        raise ValidationError('لا يمكن إنشاء أمر شراء بدون أصناف')
    purchase_order = PurchaseOrder.objects.create(
        purchase_number=generate_purchase_number(),
        supplier=supplier,
        status=status,
        order_date=order_date or timezone.localdate(),
        expected_date=expected_date,
        notes=notes,
        created_by=user,
    )
    for item in items:
        quantity = int(item['quantity'])
        unit_cost = Decimal(str(item['unit_cost']))
        if quantity <= 0:
            raise ValidationError('كمية الشراء يجب أن تكون أكبر من صفر')
        if unit_cost < 0:
            raise ValidationError('تكلفة الشراء لا يمكن أن تكون سالبة')
        PurchaseOrderItem.objects.create(
            purchase_order=purchase_order,
            product_variant=item['product_variant'],
            quantity=quantity,
            unit_cost=unit_cost,
            total_cost=unit_cost * quantity,
        )
    recalculate_purchase_order(purchase_order)
    if status != PurchaseOrder.STATUS_DRAFT:
        supplier = Supplier.objects.select_for_update().get(pk=supplier.pk)
        supplier.current_balance += purchase_order.remaining_amount
        supplier.save(update_fields=['current_balance'])
    return purchase_order


@transaction.atomic
def receive_purchase_order_items(*, purchase_order, warehouse, received_items, user, note=''):
    purchase_order = PurchaseOrder.objects.select_for_update().get(pk=purchase_order.pk)
    if purchase_order.status in {PurchaseOrder.STATUS_DRAFT, PurchaseOrder.STATUS_CANCELLED, PurchaseOrder.STATUS_RECEIVED}:
        raise ValidationError('لا يمكن استلام بضاعة لهذا الأمر في حالته الحالية')
    if not received_items:
        raise ValidationError('أدخل كميات الاستلام')

    for item_id, quantity in received_items.items():
        quantity = int(quantity or 0)
        if quantity <= 0:
            continue
        item = PurchaseOrderItem.objects.select_for_update().select_related('product_variant').get(
            pk=item_id,
            purchase_order=purchase_order,
        )
        if quantity > item.remaining_quantity:
            raise ValidationError('لا يمكن استلام كمية أكبر من المتبقي في أمر الشراء')

        stock, _ = Stock.objects.select_for_update().get_or_create(
            warehouse=warehouse,
            variant=item.product_variant,
            defaults={'quantity': 0},
        )
        stock.quantity += quantity
        stock.save(update_fields=['quantity'])
        StockMovement.objects.create(
            movement_type=StockMovement.TYPE_PURCHASE_RECEIVE,
            variant=item.product_variant,
            to_warehouse=warehouse,
            quantity=quantity,
            note=note or f'استلام من أمر الشراء {purchase_order.purchase_number}',
            created_by=user,
        )
        item.received_quantity += quantity
        item.save(update_fields=['received_quantity'])
        item.product_variant.cost_price = item.unit_cost
        item.product_variant.save(update_fields=['cost_price'])

    items = list(purchase_order.items.all())
    if all(item.received_quantity >= item.quantity for item in items):
        purchase_order.status = PurchaseOrder.STATUS_RECEIVED
    elif any(item.received_quantity > 0 for item in items):
        purchase_order.status = PurchaseOrder.STATUS_PARTIALLY_RECEIVED
    purchase_order.save(update_fields=['status'])
    return purchase_order


@transaction.atomic
def pay_supplier(*, purchase_order, amount, cash_account, user, notes=''):
    amount = Decimal(str(amount or 0))
    if amount <= 0:
        raise ValidationError('مبلغ الدفع يجب أن يكون أكبر من صفر')
    purchase_order = PurchaseOrder.objects.select_for_update().select_related('supplier').get(pk=purchase_order.pk)
    if purchase_order.status in {PurchaseOrder.STATUS_DRAFT, PurchaseOrder.STATUS_CANCELLED}:
        raise ValidationError('لا يمكن الدفع على أمر شراء مسودة أو ملغي')
    if amount > purchase_order.remaining_amount:
        raise ValidationError('مبلغ الدفع أكبر من المتبقي على أمر الشراء')

    tx = record_transaction(
        transaction_type=PaymentTransaction.TYPE_SUPPLIER_PAYMENT,
        direction=PaymentTransaction.DIRECTION_OUT,
        amount=amount,
        cash_account=cash_account,
        related_supplier=purchase_order.supplier,
        related_supplier_name=str(purchase_order.supplier),
        notes=notes or f'دفع للمورد عن أمر الشراء {purchase_order.purchase_number}',
        created_by=user,
    )
    purchase_order.paid_amount += amount
    purchase_order.remaining_amount = max(purchase_order.total_amount - purchase_order.paid_amount, Decimal('0'))
    purchase_order.save(update_fields=['paid_amount', 'remaining_amount'])
    supplier = Supplier.objects.select_for_update().get(pk=purchase_order.supplier_id)
    supplier.current_balance -= amount
    supplier.save(update_fields=['current_balance'])
    return tx


@transaction.atomic
def cancel_purchase_order(*, purchase_order, user=None):
    purchase_order = PurchaseOrder.objects.select_for_update().select_related('supplier').get(pk=purchase_order.pk)
    if purchase_order.items.filter(received_quantity__gt=0).exists():
        raise ValidationError('لا يمكن إلغاء أمر شراء تم استلام بضاعة منه')
    if purchase_order.paid_amount > 0:
        raise ValidationError('لا يمكن إلغاء أمر شراء عليه مدفوعات')
    if purchase_order.status != PurchaseOrder.STATUS_DRAFT:
        supplier = Supplier.objects.select_for_update().get(pk=purchase_order.supplier_id)
        supplier.current_balance -= purchase_order.remaining_amount
        supplier.save(update_fields=['current_balance'])
    purchase_order.status = PurchaseOrder.STATUS_CANCELLED
    purchase_order.save(update_fields=['status'])
    return purchase_order
