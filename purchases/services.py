from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from audit.models import AuditLog
from audit.services import log_audit
from finance.models import PaymentTransaction
from finance.services import record_transaction
from inventory.models import StockBatch
from inventory.services import stock_in, stock_out
from products.models import ProductVariant

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
    purchase_order.subtotal_amount = total
    discount = total * purchase_order.discount_value / Decimal('100') if purchase_order.discount_type == PurchaseOrder.DISCOUNT_PERCENT else purchase_order.discount_value
    purchase_order.discount_amount = discount.quantize(Decimal('0.01'))
    if purchase_order.discount_amount < 0 or purchase_order.discount_amount > total:
        raise ValidationError('الخصم لا يمكن أن يتجاوز إجمالي الفاتورة')
    purchase_order.total_amount = total - purchase_order.discount_amount
    purchase_order.remaining_amount = max(purchase_order.total_amount - purchase_order.paid_amount, Decimal('0'))
    purchase_order.save(update_fields=['subtotal_amount', 'discount_amount', 'total_amount', 'remaining_amount'])
    return purchase_order


@transaction.atomic
def update_purchase_discount(*, purchase_order, discount_type, discount_value, user):
    purchase_order = PurchaseOrder.objects.select_for_update().select_related('supplier').get(pk=purchase_order.pk)
    supplier = Supplier.objects.select_for_update().get(pk=purchase_order.supplier_id)
    old_remaining = purchase_order.remaining_amount
    purchase_order.discount_type = discount_type
    purchase_order.discount_value = Decimal(discount_value or 0)
    if purchase_order.discount_value < 0 or (discount_type == PurchaseOrder.DISCOUNT_PERCENT and purchase_order.discount_value > 100):
        raise ValidationError('قيمة الخصم غير صحيحة')
    recalculate_purchase_order(purchase_order)
    if purchase_order.status != PurchaseOrder.STATUS_DRAFT:
        supplier.current_balance = F('current_balance') + (purchase_order.remaining_amount - old_remaining)
        supplier.save(update_fields=['current_balance'])
    return purchase_order


@transaction.atomic
def create_purchase_order(*, supplier, items, user, status=PurchaseOrder.STATUS_ORDERED, order_date=None, invoice_datetime=None, expected_date=None, notes='', discount_type=PurchaseOrder.DISCOUNT_FIXED, discount_value=Decimal('0')):
    if status not in {PurchaseOrder.STATUS_DRAFT, PurchaseOrder.STATUS_ORDERED}:
        raise ValidationError('حالة أمر الشراء عند الإنشاء يجب أن تكون مسودة أو تم الطلب')
    if not items:
        raise ValidationError('لا يمكن إنشاء أمر شراء بدون أصناف')
    discount_value = Decimal(discount_value or 0)
    if discount_value < 0 or (discount_type == PurchaseOrder.DISCOUNT_PERCENT and discount_value > 100):
        raise ValidationError('قيمة الخصم غير صحيحة')
    if invoice_datetime and timezone.is_naive(invoice_datetime):
        invoice_datetime = timezone.make_aware(invoice_datetime, timezone.get_current_timezone())
    effective_order_date = order_date or (
        timezone.localtime(invoice_datetime).date() if invoice_datetime else timezone.localdate()
    )
    purchase_order = PurchaseOrder.objects.create(
        purchase_number=generate_purchase_number(),
        supplier=supplier,
        status=status,
        order_date=effective_order_date,
        expected_date=expected_date,
        notes=notes,
        created_by=user,
        discount_type=discount_type,
        discount_value=discount_value,
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
    if invoice_datetime:
        PurchaseOrder.objects.filter(pk=purchase_order.pk).update(created_at=invoice_datetime)
        purchase_order.created_at = invoice_datetime
    old_supplier_balance = supplier.current_balance
    if status != PurchaseOrder.STATUS_DRAFT:
        supplier = Supplier.objects.select_for_update().get(pk=supplier.pk)
        supplier.current_balance = F('current_balance') + purchase_order.remaining_amount
        supplier.save(update_fields=['current_balance'])
        supplier.refresh_from_db(fields=['current_balance'])
    
    log_audit(
        user=user,
        action=AuditLog.ACTION_CREATE,
        section=AuditLog.SECTION_PURCHASES,
        model_name='PurchaseOrder',
        object_id=purchase_order.pk,
        object_repr=str(purchase_order),
        changes_before={'supplier_balance': str(old_supplier_balance)},
        changes_after={'supplier_balance': str(supplier.current_balance)},
        notes=f'إنشاء أمر شراء: {purchase_order.purchase_number} - المورد: {supplier}',
    )
    
    return purchase_order


@transaction.atomic
def update_purchase_order(
    *,
    purchase_order,
    supplier,
    items,
    invoice_datetime,
    expected_date=None,
    notes='',
    discount_type=PurchaseOrder.DISCOUNT_FIXED,
    discount_value=Decimal('0'),
    user=None,
):
    """Safely correct a purchase invoice while preserving stock and balances."""
    purchase_order = PurchaseOrder.objects.select_for_update().select_related('supplier').get(
        pk=purchase_order.pk,
    )
    if purchase_order.status == PurchaseOrder.STATUS_CANCELLED:
        raise ValidationError('لا يمكن تعديل فاتورة شراء ملغاة')
    if not items:
        raise ValidationError('لا يمكن حفظ فاتورة بدون أصناف')

    discount_value = Decimal(str(discount_value or 0))
    if discount_value < 0 or (
        discount_type == PurchaseOrder.DISCOUNT_PERCENT and discount_value > Decimal('100')
    ):
        raise ValidationError('قيمة الخصم غير صحيحة')

    old_supplier = purchase_order.supplier
    old_remaining = purchase_order.remaining_amount
    old_status = purchase_order.status
    if old_supplier.pk != supplier.pk and purchase_order.paid_amount > 0:
        raise ValidationError('لا يمكن تغيير المورد بعد تسجيل دفعة على الفاتورة')

    locked_suppliers = {
        item.pk: item
        for item in Supplier.objects.select_for_update().filter(
            pk__in={old_supplier.pk, supplier.pk},
        ).order_by('pk')
    }
    old_supplier = locked_suppliers[old_supplier.pk]
    supplier = locked_suppliers[supplier.pk]

    existing_items = {
        item.pk: item
        for item in purchase_order.items.select_for_update().select_related('product_variant').all()
    }
    retained_ids = set()
    for posted in items:
        item_id = posted.get('item_id')
        existing = None
        if item_id not in (None, ''):
            try:
                existing = existing_items.get(int(item_id))
            except (TypeError, ValueError):
                existing = None
            if not existing:
                raise ValidationError('أحد بنود الفاتورة غير صحيح')

        try:
            variant = ProductVariant.objects.get(pk=posted['variant_id'], is_active=True)
        except ProductVariant.DoesNotExist:
            raise ValidationError('الصنف المحدد غير صحيح')
        quantity = int(posted['quantity'])
        unit_cost = Decimal(str(posted['unit_cost']))
        if quantity <= 0 or unit_cost < 0:
            raise ValidationError('بيانات الصنف غير صحيحة')

        if existing:
            retained_ids.add(existing.pk)
            if existing.received_quantity > 0 and (
                existing.product_variant_id != variant.pk or existing.quantity != quantity
            ):
                raise ValidationError('لا يمكن تغيير الصنف أو الكمية بعد استلامه؛ يمكن تصحيح سعر الشراء فقط')
            cost_changed = existing.unit_cost != unit_cost
            existing.product_variant = variant
            existing.quantity = quantity
            existing.unit_cost = unit_cost
            existing.total_cost = unit_cost * quantity
            existing.save(update_fields=['product_variant', 'quantity', 'unit_cost', 'total_cost'])
            if cost_changed and existing.received_quantity > 0:
                StockBatch.objects.filter(
                    source=purchase_order.purchase_number,
                    variant_id=existing.product_variant_id,
                ).update(unit_cost=unit_cost)
        else:
            PurchaseOrderItem.objects.create(
                purchase_order=purchase_order,
                product_variant=variant,
                quantity=quantity,
                unit_cost=unit_cost,
                total_cost=unit_cost * quantity,
            )

    for existing in existing_items.values():
        if existing.pk in retained_ids:
            continue
        if existing.received_quantity > 0:
            raise ValidationError('لا يمكن حذف صنف تم استلامه من المخزن')
        existing.delete()

    before = {
        'supplier': str(purchase_order.supplier),
        'total_amount': str(purchase_order.total_amount),
        'remaining_amount': str(old_remaining),
        'invoice_datetime': purchase_order.created_at.isoformat(),
    }
    purchase_order.supplier = supplier
    purchase_order.expected_date = expected_date
    purchase_order.notes = notes
    purchase_order.discount_type = discount_type
    purchase_order.discount_value = discount_value
    if invoice_datetime and timezone.is_naive(invoice_datetime):
        invoice_datetime = timezone.make_aware(invoice_datetime, timezone.get_current_timezone())
    if invoice_datetime:
        purchase_order.order_date = timezone.localtime(invoice_datetime).date()
    purchase_order.save(update_fields=[
        'supplier', 'expected_date', 'notes', 'discount_type', 'discount_value',
        'order_date', 'updated_at',
    ])
    recalculate_purchase_order(purchase_order)
    if purchase_order.total_amount < purchase_order.paid_amount:
        raise ValidationError('لا يمكن أن يقل إجمالي الفاتورة عن المبلغ المدفوع')

    purchase_items = list(purchase_order.items.all())
    if all(item.received_quantity >= item.quantity for item in purchase_items):
        purchase_order.status = PurchaseOrder.STATUS_RECEIVED
    elif any(item.received_quantity > 0 for item in purchase_items):
        purchase_order.status = PurchaseOrder.STATUS_PARTIALLY_RECEIVED
    else:
        purchase_order.status = PurchaseOrder.STATUS_ORDERED
    purchase_order.save(update_fields=['status', 'updated_at'])
    if invoice_datetime:
        PurchaseOrder.objects.filter(pk=purchase_order.pk).update(created_at=invoice_datetime)
        purchase_order.created_at = invoice_datetime

    if old_supplier.pk == supplier.pk:
        old_balance_effect = old_remaining if old_status != PurchaseOrder.STATUS_DRAFT else Decimal('0')
        new_balance_effect = purchase_order.remaining_amount if purchase_order.status != PurchaseOrder.STATUS_DRAFT else Decimal('0')
        if new_balance_effect != old_balance_effect:
            supplier.current_balance = F('current_balance') + (new_balance_effect - old_balance_effect)
            supplier.save(update_fields=['current_balance'])
    else:
        if old_status != PurchaseOrder.STATUS_DRAFT:
            old_supplier.current_balance = F('current_balance') - old_remaining
            old_supplier.save(update_fields=['current_balance'])
        if purchase_order.status != PurchaseOrder.STATUS_DRAFT:
            supplier.current_balance = F('current_balance') + purchase_order.remaining_amount
            supplier.save(update_fields=['current_balance'])

    after = {
        'supplier': str(supplier),
        'total_amount': str(purchase_order.total_amount),
        'remaining_amount': str(purchase_order.remaining_amount),
        'invoice_datetime': purchase_order.created_at.isoformat(),
    }
    log_audit(
        user=user,
        action=AuditLog.ACTION_UPDATE,
        section=AuditLog.SECTION_PURCHASES,
        model_name='PurchaseOrder',
        object_id=purchase_order.pk,
        object_repr=str(purchase_order),
        changes_before=before,
        changes_after=after,
        notes=f'تعديل فاتورة شراء: {purchase_order.purchase_number}',
    )
    return purchase_order


@transaction.atomic
def receive_purchase_order_items(*, purchase_order, warehouse, received_items, user, note=''):
    purchase_order = PurchaseOrder.objects.select_for_update().get(pk=purchase_order.pk)
    old_status = purchase_order.status
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

        movement = stock_in(
            variant=item.product_variant,
            warehouse=warehouse,
            quantity=quantity,
            user=user,
            note=note or f'استلام من أمر الشراء {purchase_order.purchase_number}',
            unit_cost=item.unit_cost,
            source=purchase_order.purchase_number,
        )
        movement.movement_type = movement.TYPE_PURCHASE_RECEIVE
        movement.save(update_fields=['movement_type'])
        item.received_quantity = F('received_quantity') + quantity
        item.save(update_fields=['received_quantity'])
        item.refresh_from_db(fields=['received_quantity'])
        item.product_variant.cost_price = item.unit_cost
        item.product_variant.save(update_fields=['cost_price'])

    items = list(purchase_order.items.all())
    if all(item.received_quantity >= item.quantity for item in items):
        purchase_order.status = PurchaseOrder.STATUS_RECEIVED
    elif any(item.received_quantity > 0 for item in items):
        purchase_order.status = PurchaseOrder.STATUS_PARTIALLY_RECEIVED
    purchase_order.save(update_fields=['status'])
    
    log_audit(
        user=user,
        action=AuditLog.ACTION_RECEIVE,
        section=AuditLog.SECTION_PURCHASES,
        model_name='PurchaseOrder',
        object_id=purchase_order.pk,
        object_repr=str(purchase_order),
        changes_before={'status': old_status},
        changes_after={'status': purchase_order.status},
        notes=f'استلام بضاعة من أمر الشراء {purchase_order.purchase_number}',
    )
    
    return purchase_order


@transaction.atomic
def pay_supplier(*, purchase_order, amount, cash_account, user, notes='', transaction_date=None):
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
        transaction_date=transaction_date,
    )
    purchase_order.paid_amount += amount
    purchase_order.remaining_amount = max(purchase_order.total_amount - purchase_order.paid_amount, Decimal('0'))
    purchase_order.save(update_fields=['paid_amount', 'remaining_amount'])
    supplier = Supplier.objects.select_for_update().get(pk=purchase_order.supplier_id)
    old_balance = supplier.current_balance
    supplier.current_balance -= amount
    supplier.save(update_fields=['current_balance'])
    
    log_audit(
        user=user,
        action=AuditLog.ACTION_PAY,
        section=AuditLog.SECTION_PURCHASES,
        model_name='PaymentTransaction',
        object_id=tx.pk,
        object_repr=str(tx),
        changes_before={'supplier_balance': str(old_balance)},
        changes_after={'supplier_balance': str(supplier.current_balance)},
        notes=f'دفع للمورد {purchase_order.supplier} - المبلغ: {amount}',
    )
    
    return tx


@transaction.atomic
def cancel_purchase_order(*, purchase_order, user=None):
    purchase_order = PurchaseOrder.objects.select_for_update().select_related('supplier').get(pk=purchase_order.pk)
    old_status = purchase_order.status
    if purchase_order.items.filter(received_quantity__gt=0).exists():
        raise ValidationError('لا يمكن إلغاء أمر شراء تم استلام بضاعة منه')
    if purchase_order.paid_amount > 0:
        raise ValidationError('لا يمكن إلغاء أمر شراء عليه مدفوعات')
    old_supplier_balance = purchase_order.supplier.current_balance
    if purchase_order.status != PurchaseOrder.STATUS_DRAFT:
        supplier = Supplier.objects.select_for_update().get(pk=purchase_order.supplier_id)
        supplier.current_balance = F('current_balance') - purchase_order.remaining_amount
        supplier.save(update_fields=['current_balance'])
        supplier.refresh_from_db(fields=['current_balance'])
    purchase_order.status = PurchaseOrder.STATUS_CANCELLED
    purchase_order.save(update_fields=['status'])
    
    log_audit(
        user=user,
        action=AuditLog.ACTION_CANCEL,
        section=AuditLog.SECTION_PURCHASES,
        model_name='PurchaseOrder',
        object_id=purchase_order.pk,
        object_repr=str(purchase_order),
        changes_before={
            'status': old_status,
            'supplier_balance': str(old_supplier_balance),
        },
        changes_after={
            'status': purchase_order.status,
            'supplier_balance': str(purchase_order.supplier.current_balance),
        },
        notes=f'إلغاء أمر الشراء: {purchase_order.purchase_number}',
    )
    
    return purchase_order


@transaction.atomic
def create_purchase_return(*, supplier, product_variant, warehouse, quantity, unit_cost, user, notes=''):
    quantity = int(quantity)
    unit_cost = Decimal(str(unit_cost or 0))
    if quantity <= 0:
        raise ValidationError('كمية المرتجع يجب أن تكون أكبر من صفر')
    if unit_cost < 0:
        raise ValidationError('تكلفة المرتجع لا يمكن أن تكون سالبة')
    movement = stock_out(
        variant=product_variant,
        warehouse=warehouse,
        quantity=quantity,
        user=user,
        note=notes or f'مرتجع شراء إلى المورد {supplier}',
    )
    movement.movement_type = movement.TYPE_PURCHASE_RETURN
    movement.save(update_fields=['movement_type'])
    amount = unit_cost * quantity
    supplier = Supplier.objects.select_for_update().get(pk=supplier.pk)
    supplier.current_balance = F('current_balance') - amount
    supplier.save(update_fields=['current_balance'])
    return movement
