from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from accounts.models import Branch, User
from config.branching import get_current_branch_id, get_default_branch_id
from audit.models import AuditLog
from audit.services import log_audit
from customers.models import Customer
from inventory.models import Stock, StockBatch, StockMovement, Warehouse
from inventory.services import return_stock, sale_stock
from settings_app.models import CompanySettings

from .models import Order, OrderItem


def _as_decimal(value):
    return Decimal(str(value or 0))


def _normalize_invoice_datetime(value):
    if value and timezone.is_naive(value):
        return timezone.make_aware(value, timezone.get_current_timezone())
    return value


def _set_order_created_at(order, invoice_datetime):
    invoice_datetime = _normalize_invoice_datetime(invoice_datetime)
    if not invoice_datetime:
        return
    Order.objects.filter(pk=order.pk).update(created_at=invoice_datetime)
    order.created_at = invoice_datetime


def generate_order_number(*, branch_id, order_date=None):
    """Return the next unused order number for a branch and date."""
    order_date = order_date or timezone.localdate()
    prefix = f'ORD-{order_date:%Y%m%d}-'
    numbers = Order.all_objects.filter(
        branch_id=branch_id,
        order_number__startswith=prefix,
    ).values_list('order_number', flat=True)
    highest_sequence = 0
    for number in numbers:
        suffix = number.removeprefix(prefix)
        if suffix.isdigit():
            highest_sequence = max(highest_sequence, int(suffix))
    return f'{prefix}{highest_sequence + 1:04d}'


def get_price_for_customer(variant, customer=None, order_type=None):
    if order_type == Order.TYPE_B2B:
        return getattr(variant, 'wholesale_price', None) or getattr(variant, 'sale_price', None) or Decimal('0')
    return getattr(variant, 'retail_price', None) or getattr(variant, 'sale_price', None) or Decimal('0')


def get_discount_limits(user, customer=None):
    settings = CompanySettings.load()
    if getattr(user, 'is_manager', False) or getattr(user, 'is_superuser', False):
        return Decimal('100'), settings.allow_manager_sell_below_cost
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
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError('calculate_order_totals must be called within an active transaction.')
    subtotal = Decimal('0')
    item_discounts = Decimal('0')
    total_cost = Decimal('0')
    items = list(order.items.all())
    for item in items:
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
        subtotal += line_before_discount
        item_discounts += line_discount
        total_cost += item.cost_total
    if items:
        OrderItem.objects.bulk_update(
            items,
            ['unit_price', 'discount', 'final_unit_price', 'total', 'cost_total', 'profit_total'],
            batch_size=200,
        )
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


def _build_order_items(*, order, items, user, customer, document_type):
    """Price and insert invoice lines in batches so large invoices stay fast."""
    rows = []
    subtotal_after_item_discounts = Decimal('0')
    subtotal_before_item_discounts = Decimal('0')
    item_discount_total = Decimal('0')
    is_sample = document_type == Order.DOCUMENT_SAMPLE
    for item in items:
        variant = item['variant']
        warehouse = item.get('warehouse') or order.warehouse
        stock_batch = item.get('stock_batch')
        if not warehouse:
            raise ValidationError('يجب تحديد مخزن لكل صنف في الفاتورة')
        quantity = int(item['quantity'])
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
        rows.append(OrderItem(
            branch_id=order.branch_id,
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
        ))
    if rows:
        OrderItem.objects.bulk_create(rows, batch_size=200)
    return subtotal_before_item_discounts, subtotal_after_item_discounts, item_discount_total


@transaction.atomic
def create_order(*, order_data, items, user, confirm=False, auto_collect=True):
    order_data = dict(order_data)
    invoice_datetime = order_data.pop('invoice_datetime', None)
    normalized_invoice_datetime = _normalize_invoice_datetime(invoice_datetime)
    document_type = order_data.get('document_type') or Order.DOCUMENT_SALE
    if document_type == Order.DOCUMENT_QUOTE:
        confirm = False
        auto_collect = False
    customer = order_data.get('customer')
    if not order_data.get('warehouse') and items:
        order_data['warehouse'] = items[0].get('warehouse')
    warehouse = order_data.get('warehouse')
    branch_id = (
        getattr(warehouse, 'branch_id', None)
        or getattr(customer, 'branch_id', None)
        or get_current_branch_id()
        or getattr(user, 'branch_id', None)
        or get_default_branch_id()
    )
    # The branch row is a stable lock target even when this date has no orders.
    Branch.objects.select_for_update().get(pk=branch_id)
    order_date = (
        timezone.localtime(normalized_invoice_datetime).date()
        if normalized_invoice_datetime
        else timezone.localdate()
    )
    order_discount_amount = Decimal('0') if document_type == Order.DOCUMENT_SAMPLE else _as_decimal(order_data.get('discount_amount', order_data.get('discount', 0)))
    order_discount_percentage = Decimal('0') if document_type == Order.DOCUMENT_SAMPLE else _as_decimal(order_data.get('discount_percentage', 0))
    order_data['discount_amount'] = order_discount_amount
    order_data['discount_percentage'] = order_discount_percentage
    order_data['discount'] = order_discount_amount
    if order_discount_amount > 0 or order_discount_percentage > 0:
        order_data['discount_approved_by'] = user
    order = Order.objects.create(
        order_number=generate_order_number(branch_id=branch_id, order_date=order_date),
        branch_id=branch_id,
        created_by=user,
        **order_data,
    )
    _set_order_created_at(order, invoice_datetime)
    max_discount, _ = get_discount_limits(user, customer=customer)
    subtotal_before_item_discounts, subtotal_after_item_discounts, item_discount_total = _build_order_items(
        order=order,
        items=items,
        user=user,
        customer=customer,
        document_type=document_type,
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
    if auto_collect and document_type == Order.DOCUMENT_SALE and order.total > 0 and order.payment_method != Order.METHOD_CREDIT:
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
def save_order_draft(*, order=None, order_data, items, user):
    if order is None:
        return create_order(
            order_data=order_data,
            items=items,
            user=user,
            confirm=False,
            auto_collect=False,
        )

    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.status != Order.STATUS_DRAFT:
        raise ValidationError('يمكن تعديل الفواتير المعلقة فقط')

    order_data = dict(order_data)
    invoice_datetime = order_data.pop('invoice_datetime', None)
    document_type = order_data.get('document_type') or Order.DOCUMENT_SALE
    customer = order_data.get('customer')
    if not order_data.get('warehouse') and items:
        order_data['warehouse'] = items[0].get('warehouse')

    order_discount_amount = Decimal('0') if document_type == Order.DOCUMENT_SAMPLE else _as_decimal(order_data.get('discount_amount', order_data.get('discount', 0)))
    order_discount_percentage = Decimal('0') if document_type == Order.DOCUMENT_SAMPLE else _as_decimal(order_data.get('discount_percentage', 0))
    order.document_type = document_type
    order.order_type = order_data.get('order_type') or order.order_type
    order.customer = customer
    order.warehouse = order_data.get('warehouse')
    order.payment_method = order_data.get('payment_method') or Order.METHOD_CASH
    order.wallet_from_number = order_data.get('wallet_from_number')
    order.wallet_to_number = order_data.get('wallet_to_number')
    order.discount_amount = order_discount_amount
    order.discount_percentage = order_discount_percentage
    order.discount = order_discount_amount
    order.discount_approved_by = user if order_discount_amount > 0 or order_discount_percentage > 0 else None
    order.paid_amount = Decimal('0')
    order.remaining_amount = Decimal('0')
    order.payment_status = Order.PAYMENT_UNPAID
    order.status = Order.STATUS_DRAFT
    order.save(update_fields=[
        'document_type', 'order_type', 'customer', 'warehouse', 'payment_method',
        'wallet_from_number', 'wallet_to_number', 'discount_amount', 'discount_percentage',
        'discount', 'discount_approved_by', 'paid_amount', 'remaining_amount',
        'payment_status', 'status', 'updated_at',
    ])
    _set_order_created_at(order, invoice_datetime)

    order.items.all().delete()
    max_discount, _ = get_discount_limits(user, customer=customer)
    subtotal_before_item_discounts, subtotal_after_item_discounts, item_discount_total = _build_order_items(
        order=order,
        items=items,
        user=user,
        customer=customer,
        document_type=document_type,
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
    return order


@transaction.atomic
def confirm_order(*, order, user, auto_collect=True):
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.document_type == Order.DOCUMENT_QUOTE:
        raise ValidationError('هذه فاتورة مسعرة فقط ولا تخصم من المخزون')
    if order.status != Order.STATUS_DRAFT:
        raise ValidationError('يمكن تأكيد الطلبات المسودة فقط')
    order_items = list(
        order.items.select_related('variant', 'warehouse', 'stock_batch')
        .order_by('warehouse_id', 'variant_id', 'pk')
    )
    if not order_items:
        raise ValidationError('لا يمكن تأكيد طلب بدون منتجات')
    required_stock = defaultdict(int)
    required_batches = defaultdict(int)
    for item in order_items:
        warehouse = get_order_item_warehouse(item, order=order)
        required_stock[(warehouse.pk, item.variant_id)] += item.quantity
        if item.stock_batch_id:
            required_batches[item.stock_batch_id] += item.quantity
    locked_stock = {
        (stock.warehouse_id, stock.variant_id): stock
        for stock in Stock.objects.select_for_update().filter(
            warehouse_id__in={key[0] for key in required_stock},
            variant_id__in={key[1] for key in required_stock},
        ).order_by('warehouse_id', 'variant_id')
    }
    for stock_key, quantity in required_stock.items():
        stock = locked_stock.get(stock_key)
        if not stock or stock.quantity < quantity:
            raise ValidationError('الكمية الإجمالية المطلوبة لأحد الأصناف غير متاحة')
    if required_batches:
        locked_batches = {
            batch.pk: batch
            for batch in StockBatch.objects.select_for_update()
            .filter(pk__in=required_batches)
            .order_by('pk')
        }
        for batch_id, quantity in required_batches.items():
            if batch_id not in locked_batches or locked_batches[batch_id].remaining_quantity < quantity:
                raise ValidationError('الكمية الإجمالية المطلوبة غير متاحة في إحدى دفعات السعر')
    movement_type = StockMovement.TYPE_SAMPLE if order.document_type == Order.DOCUMENT_SAMPLE else StockMovement.TYPE_SALE
    for item in order_items:
        warehouse = get_order_item_warehouse(item, order=order)
        movement = sale_stock(
            variant=item.variant,
            warehouse=warehouse,
            quantity=item.quantity,
            user=user,
            batch=item.stock_batch,
            movement_type=movement_type,
            note=f'صرف من الطلب {order.order_number}',
        )
        actual_cost_total = Decimal(str(movement.consumed_cost_total)).quantize(Decimal('0.01'))
        item.unit_cost = (actual_cost_total / item.quantity).quantize(Decimal('0.01'))
        item.cost_total = actual_cost_total
        item.profit_total = item.total - actual_cost_total
        if warehouse.warehouse_type == Warehouse.TYPE_REPRESENTATIVE and warehouse.assigned_user_id:
            from sales_reps.services import consume_sales_rep_assignments

            consume_sales_rep_assignments(
                sales_rep=warehouse.assigned_user,
                product_variant=item.variant,
                quantity=item.quantity,
            )
    OrderItem.objects.bulk_update(
        order_items,
        ['unit_cost', 'cost_total', 'profit_total'],
        batch_size=200,
    )
    cost_total = order.items.aggregate(value=Sum('cost_total'))['value'] or Decimal('0')
    order.total_cost = cost_total
    order.gross_profit = order.total - cost_total
    order.save(update_fields=['total_cost', 'gross_profit'])
    if (
        auto_collect
        and
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
    
    # Audit log
    log_audit(
        user=user,
        action=AuditLog.ACTION_CONFIRM,
        section=AuditLog.SECTION_ORDERS,
        model_name='Order',
        object_id=order.pk,
        object_repr=str(order),
        changes_before={'status': Order.STATUS_DRAFT},
        changes_after={'status': order.status},
        notes=f'تأكيد الطلب {order.order_number}',
    )
    
    return order


@transaction.atomic
def cancel_order(*, order, user):
    order = Order.objects.select_for_update().get(pk=order.pk)
    old_status = order.status
    if order.status == Order.STATUS_DRAFT:
        order.status = Order.STATUS_CANCELLED
        order.save(update_fields=['status'])
        
        log_audit(
            user=user,
            action=AuditLog.ACTION_CANCEL,
            section=AuditLog.SECTION_ORDERS,
            model_name='Order',
            object_id=order.pk,
            object_repr=str(order),
            changes_before={'status': old_status},
            changes_after={'status': order.status},
            notes=f'إلغاء الطلب المسودة {order.order_number}',
        )
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
        if warehouse.warehouse_type == Warehouse.TYPE_REPRESENTATIVE and warehouse.assigned_user_id:
            from sales_reps.services import restore_sales_rep_assignments

            restore_sales_rep_assignments(
                sales_rep=warehouse.assigned_user,
                product_variant=item.variant,
                quantity=item.quantity,
            )
    if order.document_type == Order.DOCUMENT_SALE and order.total > 0:
        from finance.services import record_order_refund

        record_order_refund(order=order, user=user, notes=f'رد تلقائي لإلغاء الطلب {order.order_number}')
    order.status = Order.STATUS_CANCELLED
    order.save(update_fields=['status'])
    
    log_audit(
        user=user,
        action=AuditLog.ACTION_CANCEL,
        section=AuditLog.SECTION_ORDERS,
        model_name='Order',
        object_id=order.pk,
        object_repr=str(order),
        changes_before={'status': old_status},
        changes_after={'status': order.status},
        notes=f'إلغاء الطلب {order.order_number}',
    )
    return order


@transaction.atomic
def return_order(*, order, user):
    # Keep the legacy endpoint safe by routing it through the canonical return
    # workflow, which adjusts stock, debt and cash together.
    from returns.models import SalesReturn
    from returns.services import (
        add_return_item,
        approve_sales_return,
        calculate_available_return_quantity,
        complete_sales_return,
        create_sales_return,
    )

    order = Order.objects.select_for_update().get(pk=order.pk)
    sales_return = create_sales_return(
        order=order,
        return_type=SalesReturn.TYPE_REFUND,
        reason=f'Full return for {order.order_number}',
        user=user,
    )
    for item in order.items.select_related('variant'):
        quantity = calculate_available_return_quantity(item)
        if quantity > 0:
            add_return_item(
                sales_return=sales_return,
                original_order_item=item,
                quantity=quantity,
                condition='good',
                return_to_stock=True,
            )
    approve_sales_return(sales_return=sales_return, user=user)
    complete_sales_return(sales_return=sales_return, user=user)
    order.refresh_from_db()
    return order


@transaction.atomic
def revise_order(*, order, order_data, items, user):
    """Replace a posted invoice while reversing and reapplying all side effects."""
    from finance.models import PaymentTransaction
    from finance.services import collect_order_payment
    from invoices.services import build_invoice_snapshot

    order = Order.objects.select_for_update().select_related('customer').get(pk=order.pk)
    editable_statuses = {
        Order.STATUS_CONFIRMED,
        Order.STATUS_PREPARING,
        Order.STATUS_READY,
        Order.STATUS_COMPLETED,
    }
    if order.document_type != Order.DOCUMENT_SALE or order.status not in editable_statuses:
        raise ValidationError('يمكن تعديل فواتير البيع المعتمدة والنشطة فقط')
    if order.sales_returns.exists():
        raise ValidationError('لا يمكن تعديل فاتورة مرتبطة بمرتجع؛ ألغِ المرتجع أولًا أو أنشئ مستند تصحيح جديدًا')

    previous_status = order.status
    previous_total = Decimal(str(order.total or 0))
    previous_paid = Decimal(str(order.paid_amount or 0))
    previous_items = list(order.items.select_related('variant', 'warehouse'))
    if any(item.variant_id is None for item in previous_items):
        raise ValidationError('لا يمكن تعديل الفاتورة لأن أحد أصنافها الأصلية لم يعد موجودًا')
    payment_account = (
        PaymentTransaction.objects.filter(related_order=order, affects_cash=True)
        .select_related('cash_account')
        .order_by('-created_at', '-pk')
        .values_list('cash_account_id', flat=True)
        .first()
    )

    for item in previous_items:
        warehouse = get_order_item_warehouse(item, order=order)
        return_stock(
            variant=item.variant,
            warehouse=warehouse,
            quantity=item.quantity,
            user=user,
            unit_cost=item.unit_cost,
            note=f'عكس مخزون لتعديل الفاتورة {order.order_number}',
        )
        if warehouse.warehouse_type == Warehouse.TYPE_REPRESENTATIVE and warehouse.assigned_user_id:
            from sales_reps.services import restore_sales_rep_assignments

            restore_sales_rep_assignments(
                sales_rep=warehouse.assigned_user,
                product_variant=item.variant,
                quantity=item.quantity,
            )

    order.status = Order.STATUS_DRAFT
    order.paid_amount = Decimal('0')
    order.remaining_amount = Decimal('0')
    order.payment_status = Order.PAYMENT_UNPAID
    order.save(update_fields=['status', 'paid_amount', 'remaining_amount', 'payment_status'])
    order = save_order_draft(
        order=order,
        order_data=order_data,
        items=items,
        user=user,
    )

    order.paid_amount = previous_paid
    order.remaining_amount = max(order.total - order.paid_amount, Decimal('0'))
    if order.paid_amount <= 0:
        order.payment_status = Order.PAYMENT_UNPAID
    elif order.remaining_amount <= 0:
        order.payment_status = Order.PAYMENT_PAID
    else:
        order.payment_status = Order.PAYMENT_PARTIAL
    order.save(update_fields=['paid_amount', 'remaining_amount', 'payment_status'])
    order = confirm_order(order=order, user=user, auto_collect=False)

    target_paid = order.total if order.payment_method != Order.METHOD_CREDIT else min(previous_paid, order.total)
    payment_delta = target_paid - previous_paid
    cash_account = None
    if payment_account:
        from finance.models import CashAccount

        cash_account = CashAccount.objects.filter(pk=payment_account).first()
    if payment_delta:
        collect_order_payment(
            order=order,
            amount=payment_delta,
            user=user,
            cash_account=cash_account,
            transaction_date=order.created_at,
            notes=f'تسوية تلقائية بعد تعديل الفاتورة {order.order_number}',
        )
        order.refresh_from_db()

    if previous_status != Order.STATUS_CONFIRMED:
        order.status = previous_status
        order.save(update_fields=['status'])

    if hasattr(order, 'invoice'):
        order.invoice.snapshot = build_invoice_snapshot(order)
        order.invoice.issued_at = order.created_at
        order.invoice.save(update_fields=['snapshot', 'issued_at'])

    log_audit(
        user=user,
        action=AuditLog.ACTION_UPDATE,
        section=AuditLog.SECTION_ORDERS,
        model_name='Order',
        object_id=order.pk,
        object_repr=str(order),
        changes_before={
            'total': str(previous_total),
            'paid_amount': str(previous_paid),
            'items_count': len(previous_items),
        },
        changes_after={
            'total': str(order.total),
            'paid_amount': str(order.paid_amount),
            'items_count': len(items),
        },
        notes=f'تعديل الفاتورة {order.order_number}',
    )
    return order
