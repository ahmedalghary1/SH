from collections import defaultdict
from decimal import Decimal
from functools import wraps

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from audit.models import AuditLog
from audit.services import log_audit
from config.branching import (
    get_current_branch_id,
    reset_current_branch,
    set_current_branch,
)
from finance.models import CashAccount, PaymentTransaction
from finance.reconciliation import assert_order_return_balance
from finance.services import record_transaction
from finance.validation import decimal_value, integer_value
from inventory.models import StockMovement, Warehouse
from inventory.services import return_stock, sale_stock
from orders.models import Order, OrderItem
from orders.services import get_order_item_warehouse

from .models import ExchangeItem, ReturnAccountSettlement, SalesReturn, SalesReturnItem


def _in_return_branch(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        branch_id = kwargs['sales_return'].branch_id
        if get_current_branch_id() not in (None, branch_id):
            raise ValidationError('المرتجع لا يتبع الفرع المحدد')
        token = set_current_branch(branch_id)
        try:
            return function(*args, **kwargs)
        finally:
            reset_current_branch(token)
    return wrapped


def _validate_return_warehouse(warehouse, branch_id):
    if warehouse and not Warehouse.objects.filter(pk=warehouse.pk, branch_id=branch_id, is_active=True).exists():
        raise ValidationError('اختر مخزنًا نشطًا من نفس فرع الفاتورة')


def _return_cash_account(sales_return, cash_account=None):
    if cash_account is None:
        previous = sales_return.financial_transactions.select_related('cash_account').order_by('-pk').first()
        cash_account = previous.cash_account if previous else CashAccount._get_or_create_single(
            branch_id=sales_return.branch_id, name='الخزنة الرئيسية',
            defaults={'account_type': CashAccount.TYPE_CASH, 'is_active': True},
        )
    if cash_account.branch_id != sales_return.branch_id or not cash_account.is_active:
        raise ValidationError('اختر خزنة نشطة من نفس فرع المرتجع')
    return cash_account


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


def customer_purchase_orders(*, customer, user):
    orders = Order.objects.filter(customer=customer, document_type=Order.DOCUMENT_SALE).exclude(
        status__in=[Order.STATUS_DRAFT, Order.STATUS_CANCELLED],
    )
    if user.role == 'sales' and not user.is_superuser:
        orders = orders.filter(created_by=user)
    return orders


def customer_purchase_rows(*, customer, user):
    """One row per variant, priced by its newest purchase, including returned sales."""
    items = OrderItem.objects.filter(
        order__in=customer_purchase_orders(customer=customer, user=user),
        variant__isnull=False,
    ).select_related('order', 'variant__product', 'variant__color', 'variant__size').order_by(
        '-order__created_at', '-order_id', '-pk',
    )
    returned = dict(SalesReturnItem.objects.filter(
        original_order_item__in=items,
        sales_return__status=SalesReturn.STATUS_COMPLETED,
    ).values('original_order_item_id').annotate(qty=Sum('quantity')).values_list('original_order_item_id', 'qty'))
    rows = {}
    for item in items:
        row = rows.setdefault(item.variant_id, {
            'variant': item.variant, 'unit_price': _line_refund_unit_price(item),
            'latest_order': item.order, 'purchased_quantity': 0,
            'available_quantity': 0, 'allocations': [],
        })
        row['purchased_quantity'] += item.quantity
        available = max(item.quantity - returned.get(item.pk, 0), 0)
        if item.order.status == Order.STATUS_RETURNED:
            available = 0
        row['available_quantity'] += available
        if available:
            row['allocations'].append((item, available))
    return list(rows.values())


@transaction.atomic
def create_customer_returns(*, customer, user, selections, reason='', return_datetime=None, return_warehouse=None):
    # Use the same order locks as completion before rebuilding available quantities.
    list(customer_purchase_orders(customer=customer, user=user).order_by('pk').select_for_update())
    rows = {row['variant'].pk: row for row in customer_purchase_rows(customer=customer, user=user)}
    if not selections:
        raise ValidationError('اختر صنفًا واحدًا على الأقل للإرجاع')
    drafts = {}
    for selection in selections:
        row = rows.get(selection['variant_id'])
        quantity = integer_value(selection['quantity'])
        if not row or quantity <= 0 or quantity > row['available_quantity']:
            raise ValidationError('كمية المرتجع غير صحيحة أو أكبر من المتاح في مشتريات العميل')
        remaining = quantity
        for item, available in row['allocations']:
            if not remaining:
                break
            if item.order_id not in drafts:
                drafts[item.order_id] = create_sales_return(
                    order=item.order, return_type=SalesReturn.TYPE_PARTIAL_RETURN,
                    reason=reason, user=user, return_datetime=return_datetime,
                    return_warehouse=return_warehouse,
                )
            allocated = min(remaining, available)
            add_return_item(
                sales_return=drafts[item.order_id], original_order_item=item,
                quantity=allocated, condition=selection['condition'],
                return_to_stock=selection['return_to_stock'],
                refund_unit_price=row['unit_price'],
                notes='مرتجع من حساب العميل بآخر سعر شراء',
            )
            remaining -= allocated
    return list(drafts.values())


@transaction.atomic
def create_sales_return(*, order, return_type, reason='', user, return_datetime=None, return_warehouse=None):
    order = Order.objects.select_for_update().get(pk=order.pk)
    _validate_return_warehouse(return_warehouse, order.branch_id)
    if return_type not in dict(SalesReturn.RETURN_TYPE_CHOICES):
        raise ValidationError('نوع المرتجع غير صحيح')
    if order.status in {Order.STATUS_DRAFT, Order.STATUS_CANCELLED, Order.STATUS_RETURNED}:
        raise ValidationError('لا يمكن إنشاء مرتجع لهذا الطلب في حالته الحالية')
    sales_return = SalesReturn.objects.create(
        order=order,
        customer=order.customer,
        return_type=return_type,
        reason=reason,
        created_by=user,
        branch_id=order.branch_id,
        return_warehouse=return_warehouse,
    )
    if return_datetime:
        if timezone.is_naive(return_datetime):
            return_datetime = timezone.make_aware(return_datetime, timezone.get_current_timezone())
        SalesReturn.objects.filter(pk=sales_return.pk).update(created_at=return_datetime)
        sales_return.created_at = return_datetime
    
    log_audit(
        user=user,
        action=AuditLog.ACTION_CREATE,
        section=AuditLog.SECTION_RETURNS,
        model_name='SalesReturn',
        object_id=sales_return.pk,
        object_repr=str(sales_return),
        changes_before={},
        changes_after={'order': str(order), 'return_type': return_type, 'created_at': sales_return.created_at.isoformat()},
        notes=f'إنشاء مرتجع للطلب {order.order_number} - النوع: {return_type}',
    )
    
    return sales_return

@transaction.atomic
def add_return_item(*, sales_return, original_order_item, quantity, condition='good', return_to_stock=True, notes='', refund_unit_price=None):
    sales_return = SalesReturn.objects.select_for_update().get(pk=sales_return.pk)
    if sales_return.status != SalesReturn.STATUS_DRAFT:
        raise ValidationError('يمكن تعديل المرتجع في حالة المسودة فقط')
    if original_order_item.order_id != sales_return.order_id:
        raise ValidationError('الصنف لا يتبع الطلب المرتبط بالمرتجع')
    quantity = integer_value(quantity)
    if quantity <= 0:
        raise ValidationError('كمية المرتجع يجب أن تكون أكبر من صفر')
    already_added = sales_return.items.filter(original_order_item=original_order_item).aggregate(v=Sum('quantity'))['v'] or 0
    available = calculate_available_return_quantity(original_order_item) - already_added
    if quantity > available:
        raise ValidationError('كمية المرتجع أكبر من الكمية المتاحة للإرجاع')
    if not original_order_item.variant:
        raise ValidationError('لا يمكن إرجاع صنف بدون متغير منتج')
    if condition not in dict(SalesReturnItem.CONDITION_CHOICES):
        raise ValidationError('حالة الصنف المرتجع غير صحيحة')

    unit_price = _line_refund_unit_price(original_order_item)
    if refund_unit_price is not None:
        unit_price = decimal_value(refund_unit_price, max_digits=12)
        if unit_price < 0:
            raise ValidationError('سعر المرتجع لا يمكن أن يكون سالبًا')
    refund_amount = unit_price * quantity
    item = SalesReturnItem.objects.create(
        branch_id=sales_return.branch_id,
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
    quantity = integer_value(quantity)
    if quantity <= 0:
        raise ValidationError('كمية الاستبدال يجب أن تكون أكبر من صفر')
    if quantity > calculate_available_return_quantity(old_order_item):
        raise ValidationError('كمية الاستبدال أكبر من الكمية المتاحة للإرجاع')

    returned_in_this_exchange = sales_return.items.filter(original_order_item=old_order_item).aggregate(v=Sum('quantity'))['v'] or 0
    already_exchanged = sales_return.exchange_items.filter(old_order_item=old_order_item).aggregate(v=Sum('quantity'))['v'] or 0
    if already_exchanged + quantity > returned_in_this_exchange:
        raise ValidationError('كمية الاستبدال أكبر من كمية الصنف المرتجع في هذا المرتجع')

    old_unit_price = _line_refund_unit_price(old_order_item)
    new_unit_price = decimal_value(new_unit_price, max_digits=10)
    if new_unit_price < 0:
        raise ValidationError('سعر صنف الاستبدال لا يمكن أن يكون سالبًا')
    price_difference = (new_unit_price - old_unit_price) * quantity
    item = ExchangeItem.objects.create(
        branch_id=sales_return.branch_id,
        sales_return=sales_return,
        old_order_item=old_order_item,
        new_product_variant=new_product_variant,
        quantity=quantity,
        new_unit_price=new_unit_price,
        old_unit_price=old_unit_price,
        price_difference=price_difference,
        notes=notes,
    )
    sales_return.revision += 1
    sales_return.save(update_fields=['revision'])
    
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
    if sales_return.return_type == SalesReturn.TYPE_EXCHANGE and not sales_return.exchange_items.exists():
        raise ValidationError('لا يمكن اعتماد استبدال بدون أصناف جديدة')
    sales_return.status = SalesReturn.STATUS_APPROVED
    sales_return.revision += 1
    sales_return.approved_by = user
    sales_return.save(update_fields=['status', 'approved_by', 'revision'])
    
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
@_in_return_branch
def complete_sales_return(*, sales_return, user, cash_account=None, return_warehouse=Ellipsis, settlement_method='cash'):
    if settlement_method not in {'cash', 'account'}:
        raise ValidationError('طريقة تسوية المرتجع غير صحيحة')
    sales_return = SalesReturn.objects.select_for_update().get(pk=sales_return.pk)
    old_status = sales_return.status
    if sales_return.status != SalesReturn.STATUS_APPROVED:
        raise ValidationError('يجب اعتماد المرتجع قبل إكماله')
    if return_warehouse is not Ellipsis:
        sales_return.return_warehouse = return_warehouse
        sales_return.save(update_fields=['return_warehouse'])

    if settlement_method == 'account' and sales_return.customer_id:
        list(Order.objects.select_for_update().filter(customer_id=sales_return.customer_id).order_by('pk'))
    order = Order.objects.select_for_update().get(pk=sales_return.order_id)
    _validate_return_warehouse(sales_return.return_warehouse, order.branch_id)
    if order.status in {Order.STATUS_DRAFT, Order.STATUS_CANCELLED, Order.STATUS_RETURNED}:
        raise ValidationError('حالة الطلب الحالية لا تسمح بإكمال المرتجع')
    sales_return.order_status_before_return = _order_status_before_returns(order)
    # Other pending returns may have completed since this one was drafted.
    # Recheck aggregated quantities under the order lock before any side effect.
    requested = sales_return.items.values('original_order_item_id').annotate(quantity=Sum('quantity'))
    for row in requested:
        original_item = order.items.get(pk=row['original_order_item_id'])
        if row['quantity'] > calculate_available_return_quantity(original_item):
            raise ValidationError('كمية المرتجع أكبر من الكمية المتبقية المتاحة للإرجاع')
    for item in sales_return.items.select_related('product_variant', 'original_order_item__warehouse'):
        item_warehouse = sales_return.return_warehouse or get_order_item_warehouse(item.original_order_item, order=order)
        if item.condition == SalesReturnItem.CONDITION_GOOD and item.return_to_stock:
            _increase_stock_for_return(order=order, item=item, user=user, warehouse=item_warehouse)
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
    _process_refund(sales_return=sales_return, order=order, user=user, cash_account=cash_account,
                    settlement_method=settlement_method)

    sales_return.status = SalesReturn.STATUS_COMPLETED
    sales_return.revision += 1
    sales_return.completed_by = user
    sales_return.save(update_fields=['status', 'completed_by', 'revision', 'order_status_before_return'])
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


def _increase_stock_for_return(*, order, item, user, warehouse=None):
    warehouse = warehouse or get_order_item_warehouse(item.original_order_item, order=order)
    movement = return_stock(
        variant=item.product_variant,
        warehouse=warehouse,
        quantity=item.quantity,
        unit_cost=item.original_order_item.unit_cost,
        note=f'Sales return for order {order.order_number}',
        user=user,
    )
    movement.movement_type = StockMovement.TYPE_SALES_RETURN
    movement.save(update_fields=['movement_type'])
    if warehouse.warehouse_type == warehouse.TYPE_REPRESENTATIVE and warehouse.assigned_user_id:
        from sales_reps.services import restore_sales_rep_assignments

        restore_sales_rep_assignments(
            sales_rep=warehouse.assigned_user,
            product_variant=item.product_variant,
            quantity=item.quantity,
        )


def _process_refund(*, sales_return, order, user, cash_account, settlement_method='cash'):
    if sales_return.return_type == SalesReturn.TYPE_EXCHANGE:
        return None
    refund_amount = sales_return.items.aggregate(v=Sum('refund_amount'))['v'] or Decimal('0')
    if refund_amount <= 0:
        return None
    current_remaining = Decimal(str(order.remaining_amount or 0))
    debt_reduction = min(refund_amount, current_remaining)
    cash_refund = refund_amount - debt_reduction
    sales_return.debt_reduction = debt_reduction
    sales_return.save(update_fields=['debt_reduction'])
    if debt_reduction > 0:
        order.remaining_amount = current_remaining - debt_reduction
        if order.remaining_amount <= 0:
            order.payment_status = Order.PAYMENT_PAID
        elif order.paid_amount > 0:
            order.payment_status = Order.PAYMENT_PARTIAL
        else:
            order.payment_status = Order.PAYMENT_UNPAID
        order.save(update_fields=['remaining_amount', 'payment_status'])
    if cash_refund <= 0:
        return None
    if settlement_method == 'account':
        settlement = ReturnAccountSettlement.objects.create(
            branch_id=sales_return.branch_id, sales_return=sales_return, amount=cash_refund, created_by=user,
            reason='تسوية المرتجع على حساب العميل دون صرف نقدي',
        )
        from .settlements import allocate_return_credit

        allocate_return_credit(settlement, user=user, cash_account=_return_cash_account(sales_return, cash_account))
        return None
    if settlement_method != 'cash':
        raise ValidationError('طريقة تسوية المرتجع غير صحيحة')
    payment = record_transaction(
        transaction_type=PaymentTransaction.TYPE_REFUND,
        direction=PaymentTransaction.DIRECTION_OUT,
        amount=cash_refund,
        cash_account=_return_cash_account(sales_return, cash_account),
        related_order=order,
        related_customer=sales_return.customer,
        notes=f'Refund for return {sales_return.pk} / order {order.order_number}',
        created_by=user,
        transaction_date=sales_return.created_at,
    )
    sales_return.financial_transactions.add(payment)
    return payment


def _process_exchange_stock_and_money(*, sales_return, order, user, cash_account):
    for exchange in sales_return.exchange_items.select_related('new_product_variant', 'old_order_item__warehouse'):
        warehouse = get_order_item_warehouse(exchange.old_order_item, order=order)
        sale_stock(
            variant=exchange.new_product_variant,
            warehouse=warehouse,
            quantity=exchange.quantity,
            movement_type=StockMovement.TYPE_EXCHANGE_OUT,
            note=f'Exchange out for order {order.order_number}',
            user=user,
        )
        if warehouse.warehouse_type == warehouse.TYPE_REPRESENTATIVE and warehouse.assigned_user_id:
            from sales_reps.services import consume_sales_rep_assignments

            consume_sales_rep_assignments(
                sales_rep=warehouse.assigned_user,
                product_variant=exchange.new_product_variant,
                quantity=exchange.quantity,
            )
        if exchange.price_difference > 0:
            payment = record_transaction(
                transaction_type=PaymentTransaction.TYPE_CUSTOMER_PAYMENT,
                direction=PaymentTransaction.DIRECTION_IN,
                amount=exchange.price_difference,
                cash_account=_return_cash_account(sales_return, cash_account),
                related_order=order,
                related_customer=sales_return.customer,
                notes=f'Exchange price difference for return {sales_return.pk}',
                created_by=user,
                transaction_date=sales_return.created_at,
            )
            sales_return.financial_transactions.add(payment)
        elif exchange.price_difference < 0:
            payment = record_transaction(
                transaction_type=PaymentTransaction.TYPE_REFUND,
                direction=PaymentTransaction.DIRECTION_OUT,
                amount=abs(exchange.price_difference),
                cash_account=_return_cash_account(sales_return, cash_account),
                related_order=order,
                related_customer=sales_return.customer,
                notes=f'Exchange refund difference for return {sales_return.pk}',
                created_by=user,
                transaction_date=sales_return.created_at,
            )
            sales_return.financial_transactions.add(payment)


def _recalculate_refund_amount(sales_return):
    total = sales_return.items.aggregate(v=Sum('refund_amount'))['v'] or Decimal('0')
    sales_return.refund_amount = total
    sales_return.revision += 1
    sales_return.save(update_fields=['refund_amount', 'revision'])
    return total


def _return_stock_positions(order, items, exchanges, warehouse):
    positions = {}
    for item in items:
        if item.condition != SalesReturnItem.CONDITION_GOOD or not item.return_to_stock:
            continue
        target = warehouse or get_order_item_warehouse(item.original_order_item, order=order)
        key = (target.pk, item.product_variant_id)
        position = positions.setdefault(key, [target, item.product_variant, 0, item.original_order_item.unit_cost])
        position[2] += item.quantity
    for item in exchanges:
        source = get_order_item_warehouse(item.old_order_item, order=order)
        key = (source.pk, item.new_product_variant_id)
        position = positions.setdefault(key, [source, item.new_product_variant, 0, item.new_product_variant.cost_price])
        position[2] -= item.quantity
    return positions


def _apply_return_stock_changes(*, sales_return, before, after, user):
    changes = []
    for key in sorted(before.keys() | after.keys()):
        warehouse, variant, _quantity, unit_cost = after.get(key, before.get(key))
        delta = after.get(key, [None, None, 0])[2] - before.get(key, [None, None, 0])[2]
        if delta:
            changes.append((warehouse, variant, delta, unit_cost))
    # Withdraw first so changing warehouses cannot hide a shortage at source.
    for warehouse, variant, delta, unit_cost in sorted(changes, key=lambda row: row[2] > 0):
        note = f'Adjustment for sales return {sales_return.pk}'
        if delta < 0:
            sale_stock(variant=variant, warehouse=warehouse, quantity=-delta,
                       user=user, note=note, movement_type=StockMovement.TYPE_ADJUSTMENT)
        else:
            movement = return_stock(variant=variant, warehouse=warehouse, quantity=delta,
                                    user=user, note=note, unit_cost=unit_cost)
            movement.movement_type = StockMovement.TYPE_ADJUSTMENT
            movement.save(update_fields=['movement_type'])
        if warehouse.warehouse_type == Warehouse.TYPE_REPRESENTATIVE and warehouse.assigned_user_id:
            from sales_reps.services import (
                consume_sales_rep_assignments,
                restore_sales_rep_assignments,
            )

            adjust = restore_sales_rep_assignments if delta > 0 else consume_sales_rep_assignments
            adjust(sales_rep=warehouse.assigned_user, product_variant=variant, quantity=abs(delta))


def _record_return_edit_payment(sales_return, order, amount, user, cash_account):
    if not amount:
        return
    payment = record_transaction(
        transaction_type=PaymentTransaction.TYPE_REFUND if amount > 0 else PaymentTransaction.TYPE_CUSTOMER_PAYMENT,
        direction=PaymentTransaction.DIRECTION_OUT if amount > 0 else PaymentTransaction.DIRECTION_IN,
        amount=abs(amount), cash_account=_return_cash_account(sales_return, cash_account),
        related_order=order, related_customer=sales_return.customer,
        notes=f'تعديل مرتجع #{sales_return.pk}', created_by=user,
        transaction_date=sales_return.created_at,
    )
    sales_return.financial_transactions.add(payment)


def _record_damaged_changes(sales_return, order, old_items, new_items, old_warehouse, new_warehouse, user):
    positions = {}
    for items, warehouse, sign in ((old_items, old_warehouse, -1), (new_items, new_warehouse, 1)):
        for item in items:
            if item.condition != SalesReturnItem.CONDITION_DAMAGED:
                continue
            target = warehouse or get_order_item_warehouse(item.original_order_item, order=order)
            key = (target.pk, item.product_variant_id)
            entry = positions.setdefault(key, [target, item.product_variant, 0])
            entry[2] += sign * item.quantity
    for warehouse, variant, delta in positions.values():
        if delta:
            StockMovement.objects.create(
                movement_type=StockMovement.TYPE_DAMAGED_RETURN, variant=variant,
                from_warehouse=warehouse if delta < 0 else None,
                to_warehouse=warehouse if delta > 0 else None, quantity=abs(delta),
                note=f'Damaged return adjustment for return {sales_return.pk}', created_by=user,
            )


@transaction.atomic
@_in_return_branch
def update_sales_return(*, sales_return, user, revision, items, exchanges=None,
                        reason='', return_datetime=None, return_warehouse=None, cash_account=None):
    sales_return = SalesReturn.objects.select_for_update().get(pk=sales_return.pk)
    if sales_return.status == SalesReturn.STATUS_CANCELLED:
        raise ValidationError('لا يمكن تعديل مرتجع ملغى')
    manager = user.is_superuser or user.role in {'manager', 'director'}
    if not manager and not (user.role == 'sales' and sales_return.created_by_id == user.pk
                            and sales_return.status == SalesReturn.STATUS_DRAFT):
        raise ValidationError('لا تملك صلاحية تعديل هذا المرتجع')
    if sales_return.revision != revision:
        raise ValidationError('تم تغيير المرتجع أثناء التعديل. أعد تحميل الصفحة ثم حاول مرة أخرى')
    order = Order.objects.select_for_update().get(pk=sales_return.order_id)
    if order.status in {Order.STATUS_CANCELLED, Order.STATUS_DRAFT}:
        raise ValidationError('لا يمكن تعديل مرتجع لفاتورة ملغاة أو مسودة')
    assert_order_return_balance(order)
    _validate_return_warehouse(return_warehouse, order.branch_id)
    old_items = list(sales_return.items.select_related('original_order_item__warehouse', 'product_variant'))
    old_exchanges = list(sales_return.exchange_items.select_related('old_order_item__warehouse', 'new_product_variant'))
    old_by_id = {item.pk: item for item in old_items}
    new_items, used_ids, quantities = [], set(), defaultdict(int)
    for row in items:
        item_id = row.get('item_id')
        original = order.items.select_related('variant', 'warehouse').filter(pk=row['original_order_item'].pk).first()
        if not original or not original.variant_id:
            raise ValidationError('الصنف لا يتبع فاتورة المرتجع')
        old = old_by_id.get(item_id)
        if item_id and (not old or item_id in used_ids or old.original_order_item_id != original.pk):
            raise ValidationError('بيانات صنف المرتجع غير صحيحة')
        if item_id:
            used_ids.add(item_id)
        quantity = integer_value(row['quantity'], minimum=0)
        if not quantity:
            continue
        condition = row['condition']
        if condition not in dict(SalesReturnItem.CONDITION_CHOICES):
            raise ValidationError('حالة الصنف غير صحيحة')
        quantities[original.pk] += quantity
        unit_price = old.refund_amount / old.quantity if old else _line_refund_unit_price(original)
        new_items.append(SalesReturnItem(
            pk=item_id, branch_id=sales_return.branch_id, sales_return=sales_return,
            original_order_item=original, product_variant=original.variant, quantity=quantity,
            condition=condition, return_to_stock=bool(row.get('return_to_stock')),
            refund_amount=decimal_value(unit_price * quantity, max_digits=12), notes=row.get('notes', ''),
        ))
    if not new_items:
        raise ValidationError('أضف صنفًا واحدًا بكمية أكبر من صفر على الأقل')
    for original_id, quantity in quantities.items():
        returned = SalesReturnItem.objects.filter(
            original_order_item_id=original_id, sales_return__status=SalesReturn.STATUS_COMPLETED,
        ).exclude(sales_return=sales_return).aggregate(v=Sum('quantity'))['v'] or 0
        if quantity + returned > order.items.get(pk=original_id).quantity:
            raise ValidationError('كمية المرتجع أكبر من المتاح للإرجاع')
    new_exchanges, exchanged = [], defaultdict(int)
    if sales_return.return_type == SalesReturn.TYPE_EXCHANGE:
        old_exchange_ids = {item.pk for item in old_exchanges}
        exchange_ids = set()
        for row in exchanges or []:
            exchange_id = row.get('item_id')
            if exchange_id and (exchange_id not in old_exchange_ids or exchange_id in exchange_ids):
                raise ValidationError('بيانات الاستبدال غير صحيحة')
            if exchange_id:
                exchange_ids.add(exchange_id)
            quantity = integer_value(row['quantity'], minimum=0)
            if not quantity:
                continue
            original = order.items.filter(pk=row['old_order_item'].pk).first()
            variant = row['new_product_variant']
            if not original or variant.branch_id != order.branch_id or not variant.is_active:
                raise ValidationError('صنف الاستبدال غير صحيح أو من فرع مختلف')
            exchanged[original.pk] += quantity
            price = decimal_value(row['new_unit_price'], max_digits=10)
            if price < 0:
                raise ValidationError('السعر لا يمكن أن يكون سالبًا')
            old_price = _line_refund_unit_price(original)
            new_exchanges.append(ExchangeItem(
                pk=exchange_id, branch_id=sales_return.branch_id, sales_return=sales_return,
                old_order_item=original, new_product_variant=variant, quantity=quantity,
                old_unit_price=old_price, new_unit_price=price,
                price_difference=(price - old_price) * quantity, notes=row.get('notes', ''),
            ))
        if ((not new_exchanges and sales_return.status == SalesReturn.STATUS_COMPLETED)
                or any(qty > quantities[key] for key, qty in exchanged.items())):
            raise ValidationError('كميات الاستبدال يجب ألا تتجاوز كميات الأصناف المرتجعة')
    was_completed = sales_return.status == SalesReturn.STATUS_COMPLETED
    old_amount = sales_return.refund_amount
    new_amount = decimal_value(sum((item.refund_amount for item in new_items), Decimal(0)), max_digits=12)
    if new_amount != old_amount and ReturnAccountSettlement.objects.filter(sales_return=sales_return).exists():
        raise ValidationError('هذا المرتجع تمت تسويته على حساب العميل. لإعادة تحديد قيمته ألغِه ثم أنشئ مرتجعًا جديدًا')
    before = {'refund_amount': str(old_amount), 'warehouse': sales_return.return_warehouse_id,
              'created_at': sales_return.created_at.isoformat(), 'status': sales_return.status,
              'items': [{'id': item.pk, 'quantity': item.quantity, 'condition': item.condition,
                         'return_to_stock': item.return_to_stock} for item in old_items]}
    if was_completed:
        old_positions = _return_stock_positions(order, old_items, old_exchanges, sales_return.return_warehouse)
        new_positions = _return_stock_positions(order, new_items, new_exchanges, return_warehouse)
        _apply_return_stock_changes(sales_return=sales_return, before=old_positions, after=new_positions, user=user)
        _record_damaged_changes(sales_return, order, old_items, new_items,
                                sales_return.return_warehouse, return_warehouse, user)
    if return_datetime:
        if timezone.is_naive(return_datetime):
            return_datetime = timezone.make_aware(return_datetime)
        sales_return.created_at = return_datetime
    if was_completed:
        if sales_return.return_type == SalesReturn.TYPE_EXCHANGE:
            difference = sum((item.price_difference for item in new_exchanges), Decimal(0)) - sum(
                (item.price_difference for item in old_exchanges), Decimal(0))
            _record_return_edit_payment(sales_return, order, -difference, user, cash_account)
        else:
            delta = new_amount - old_amount
            if delta > 0:
                debt = min(delta, order.remaining_amount)
                cash_delta = delta - debt
            else:
                cash_reversal = min(-delta, old_amount - sales_return.debt_reduction)
                cash_delta = -cash_reversal
                debt = delta + cash_reversal
            order.remaining_amount -= debt
            sales_return.debt_reduction += debt
            _record_return_edit_payment(sales_return, order, cash_delta, user, cash_account)
            order.payment_status = (Order.PAYMENT_PAID if order.remaining_amount <= 0 else
                                    Order.PAYMENT_PARTIAL if order.paid_amount > 0 else Order.PAYMENT_UNPAID)
            order.save(update_fields=['remaining_amount', 'payment_status'])
        local_datetime = timezone.localtime(sales_return.created_at)
        sales_return.financial_transactions.update(transaction_date=local_datetime.date(), transaction_time=local_datetime.time())
    elif sales_return.status != SalesReturn.STATUS_DRAFT:
        sales_return.status = SalesReturn.STATUS_DRAFT
        sales_return.approved_by = None
    # Preserve row IDs: other records may refer to existing return lines.
    sales_return.items.exclude(pk__in=[item.pk for item in new_items if item.pk]).delete()
    for item in new_items:
        item.save()
    sales_return.exchange_items.exclude(pk__in=[item.pk for item in new_exchanges if item.pk]).delete()
    for item in new_exchanges:
        item.save()
    sales_return.reason = reason
    sales_return.return_warehouse = return_warehouse
    sales_return.refund_amount = new_amount
    sales_return.revision += 1
    sales_return.save()
    if was_completed:
        _update_order_return_status(order)
    log_audit(user=user, action=AuditLog.ACTION_UPDATE, section=AuditLog.SECTION_RETURNS,
              model_name='SalesReturn', object_id=sales_return.pk, object_repr=str(sales_return),
              changes_before=before,
              changes_after={'refund_amount': str(new_amount), 'warehouse': sales_return.return_warehouse_id,
                             'created_at': sales_return.created_at.isoformat(), 'status': sales_return.status,
                             'items': [{'id': item.pk, 'quantity': item.quantity, 'condition': item.condition,
                                        'return_to_stock': item.return_to_stock} for item in new_items]},
              notes=f'تعديل المرتجع #{sales_return.pk}')
    return sales_return


def _order_status_before_returns(order):
    if order.status not in {Order.STATUS_RETURNED, Order.STATUS_PARTIALLY_RETURNED}:
        return order.status
    previous = order.sales_returns.filter(status=SalesReturn.STATUS_COMPLETED).exclude(order_status_before_return__in=[
        '', Order.STATUS_RETURNED, Order.STATUS_PARTIALLY_RETURNED,
        Order.STATUS_DRAFT, Order.STATUS_CANCELLED,
    ]).order_by('pk').values_list('order_status_before_return', flat=True).first()
    return previous or Order.STATUS_COMPLETED


@transaction.atomic
@_in_return_branch
def cancel_sales_return(*, sales_return, user, revision=None, reason=''):
    if not user.is_superuser and user.role not in {'manager', 'director'}:
        raise ValidationError('لا تملك صلاحية إلغاء المرتجعات')
    sales_return = SalesReturn.objects.select_for_update().get(pk=sales_return.pk)
    if sales_return.status == SalesReturn.STATUS_CANCELLED:
        return sales_return
    if revision is not None and sales_return.revision != revision:
        raise ValidationError('تم تغيير المرتجع. أعد تحميل الصفحة قبل الإلغاء')
    settlement = ReturnAccountSettlement.objects.filter(sales_return=sales_return).first()
    if settlement and sales_return.customer_id:
        list(Order.objects.select_for_update().filter(customer_id=sales_return.customer_id).order_by('pk'))
    order = Order.objects.select_for_update().get(pk=sales_return.order_id)
    old_status = sales_return.status
    restore_status = sales_return.order_status_before_return or _order_status_before_returns(order)
    if old_status == SalesReturn.STATUS_COMPLETED:
        if order.status in {Order.STATUS_DRAFT, Order.STATUS_CANCELLED}:
            raise ValidationError('لا يمكن إلغاء مرتجع مكتمل لفاتورة ملغاة أو مسودة')
        assert_order_return_balance(order)
        items = list(sales_return.items.select_related('original_order_item__warehouse', 'product_variant'))
        exchanges = list(sales_return.exchange_items.select_related('old_order_item__warehouse', 'new_product_variant'))
        payments = list(sales_return.financial_transactions.select_for_update().filter(affects_cash=True))
        cash_effects = defaultdict(lambda: Decimal(0))
        for payment in payments:
            cash_effects[payment.cash_account_id] += (
                payment.amount if payment.direction == PaymentTransaction.DIRECTION_IN else -payment.amount
            )
        expected_effect = (sum((item.price_difference for item in exchanges), Decimal(0))
                           if sales_return.return_type == SalesReturn.TYPE_EXCHANGE
                           else sales_return.debt_reduction - sales_return.refund_amount
                           + (settlement.amount if settlement else Decimal(0)))
        if sum(cash_effects.values(), Decimal(0)) != expected_effect:
            raise ValidationError('تعذر مطابقة الحركات المالية للمرتجع. يجب مراجعتها قبل الإلغاء')
        if settlement:
            from .settlements import reverse_return_credit

            reverse_return_credit(settlement, user=user)
        positions = _return_stock_positions(order, items, exchanges, sales_return.return_warehouse)
        _apply_return_stock_changes(sales_return=sales_return, before=positions, after={}, user=user)
        _record_damaged_changes(sales_return, order, items, [],
                                sales_return.return_warehouse, sales_return.return_warehouse, user)

        # Reverse the net cash effect separately in every original account.
        # Keep original and reversal rows for the cash ledger and audit history.
        accounts = {account.pk: account for account in CashAccount.objects.select_for_update().filter(
            pk__in=cash_effects,
        ).order_by('pk')}
        if len(accounts) != len(cash_effects):
            raise ValidationError('إحدى خزن المرتجع لا تتبع فرع الفاتورة')
        for account_id in sorted(cash_effects):
            effect = cash_effects[account_id]
            if not effect:
                continue
            payment = record_transaction(
                transaction_type=PaymentTransaction.TYPE_ADJUSTMENT,
                direction=PaymentTransaction.DIRECTION_OUT if effect > 0 else PaymentTransaction.DIRECTION_IN,
                amount=abs(effect), cash_account=accounts[account_id], related_order=order,
                related_customer=sales_return.customer, created_by=user,
                notes=f'إلغاء المرتجع #{sales_return.pk}',
            )
            sales_return.financial_transactions.add(payment)
        if sales_return.return_type != SalesReturn.TYPE_EXCHANGE:
            order.remaining_amount += sales_return.debt_reduction
            order.payment_status = (Order.PAYMENT_PAID if order.remaining_amount <= 0 else
                                    Order.PAYMENT_PARTIAL if order.paid_amount > 0 else Order.PAYMENT_UNPAID)
            order.save(update_fields=['remaining_amount', 'payment_status'])

    sales_return.status = SalesReturn.STATUS_CANCELLED
    sales_return.cancelled_by = user
    sales_return.cancelled_at = timezone.now()
    sales_return.cancellation_reason = reason
    sales_return.revision += 1
    sales_return.save(update_fields=['status', 'cancelled_by', 'cancelled_at', 'cancellation_reason', 'revision'])
    if old_status == SalesReturn.STATUS_COMPLETED:
        _update_order_return_status(order, fallback_status=restore_status)
    log_audit(
        user=user, action=AuditLog.ACTION_CANCEL, section=AuditLog.SECTION_RETURNS,
        model_name='SalesReturn', object_id=sales_return.pk, object_repr=str(sales_return),
        changes_before={'status': old_status, 'refund_amount': str(sales_return.refund_amount)},
        changes_after={'status': sales_return.status}, notes=reason or f'إلغاء المرتجع #{sales_return.pk}',
    )
    return sales_return


def _update_order_return_status(order, *, fallback_status=None):
    total_quantity = order.items.aggregate(v=Sum('quantity'))['v'] or 0
    returned_quantity = SalesReturnItem.objects.filter(
        original_order_item__order=order,
        sales_return__status=SalesReturn.STATUS_COMPLETED,
    ).aggregate(v=Sum('quantity'))['v'] or 0
    if returned_quantity >= total_quantity and total_quantity > 0:
        order.status = Order.STATUS_RETURNED
    elif returned_quantity > 0:
        order.status = Order.STATUS_PARTIALLY_RETURNED
    elif order.status in {Order.STATUS_RETURNED, Order.STATUS_PARTIALLY_RETURNED}:
        order.status = fallback_status or _order_status_before_returns(order)
    order.save(update_fields=['status'])
