from decimal import Decimal
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from audit.models import AuditLog
from audit.services import log_audit

from .models import CashAccount, PaymentTransaction


def _as_decimal(amount):
    amount = Decimal(str(amount or 0))
    if amount <= 0:
        raise ValidationError('المبلغ يجب أن يكون أكبر من صفر')
    return amount


def _locked_account(account):
    if account is None:
        account = CashAccount.get_default()
    return CashAccount.objects.select_for_update().get(pk=account.pk)


@transaction.atomic
def record_transaction(
    *,
    transaction_type,
    direction,
    amount,
    cash_account=None,
    related_order=None,
    related_customer=None,
    related_sales_rep=None,
    related_supplier=None,
    related_supplier_name='',
    notes='',
    created_by=None,
    reference='',
    transaction_date=None,
):
    amount = _as_decimal(amount)
    account = _locked_account(cash_account)
    old_balance = account.balance
    if direction == PaymentTransaction.DIRECTION_IN:
        account.balance = F('balance') + amount
    elif direction == PaymentTransaction.DIRECTION_OUT:
        if not account.allow_overdraft and account.balance < amount:
            raise ValidationError('رصيد الخزنة غير كاف لتنفيذ الحركة')
        account.balance = F('balance') - amount
    else:
        raise ValidationError('اتجاه الحركة المالية غير صحيح')
    account.save(update_fields=['balance'])
    account.refresh_from_db(fields=['balance'])
    tx = PaymentTransaction.objects.create(
        transaction_type=transaction_type,
        direction=direction,
        amount=amount,
        cash_account=account,
        related_order=related_order,
        related_customer=related_customer,
        related_sales_rep=related_sales_rep,
        related_supplier=related_supplier,
        related_supplier_name=related_supplier_name or '',
        notes=notes,
        transaction_date=transaction_date or timezone.localdate(),
        created_by=created_by,
        reference=reference or '',
    )
    
    # Determine section based on transaction type
    section = AuditLog.SECTION_FINANCE
    action = AuditLog.ACTION_PAY if direction == PaymentTransaction.DIRECTION_OUT else AuditLog.ACTION_COLLECT
    
    log_audit(
        user=created_by,
        action=action,
        section=section,
        model_name='PaymentTransaction',
        object_id=tx.pk,
        object_repr=str(tx),
        changes_before={'account_balance': str(old_balance)},
        changes_after={'account_balance': str(account.balance)},
        notes=f'{tx.get_transaction_type_display()} - المبلغ: {amount}',
    )
    
    return tx


def record_customer_payment(*, order, customer, amount, user, cash_account=None, notes='', transaction_date=None):
    amount = _as_decimal(amount)
    if order and amount > order.remaining_amount + order.paid_amount:
        raise ValidationError('مبلغ التحصيل أكبر من قيمة الطلب')
    return record_transaction(
        transaction_type=PaymentTransaction.TYPE_CUSTOMER_PAYMENT,
        direction=PaymentTransaction.DIRECTION_IN,
        amount=amount,
        cash_account=cash_account,
        related_order=order,
        related_customer=customer,
        notes=notes,
        created_by=user,
        transaction_date=transaction_date,
    )


@transaction.atomic
def record_supplier_payment(*, supplier, amount, user, cash_account=None, notes='', transaction_date=None):
    from purchases.models import Supplier

    amount = _as_decimal(amount)
    supplier = Supplier.objects.select_for_update().get(pk=supplier.pk)
    tx = record_transaction(
        transaction_type=PaymentTransaction.TYPE_SUPPLIER_PAYMENT,
        direction=PaymentTransaction.DIRECTION_OUT,
        amount=amount,
        cash_account=cash_account,
        related_supplier=supplier,
        related_supplier_name=str(supplier),
        notes=notes or f'دفع للمورد {supplier}',
        created_by=user,
        transaction_date=transaction_date,
    )
    supplier.current_balance = F('current_balance') - amount
    supplier.save(update_fields=['current_balance'])
    return tx


@transaction.atomic
def record_order_sale_payment(*, order, user, cash_account=None, notes=''):
    from orders.models import Order

    order = Order.objects.select_for_update().get(pk=order.pk)
    target_amount = Decimal(str(order.total or 0))
    if target_amount <= 0:
        return None

    already_recorded = PaymentTransaction.objects.filter(
        related_order=order,
        transaction_type=PaymentTransaction.TYPE_CUSTOMER_PAYMENT,
        direction=PaymentTransaction.DIRECTION_IN,
    ).aggregate(v=Sum('amount'))['v'] or Decimal('0')
    amount_to_record = target_amount - already_recorded
    if amount_to_record <= 0:
        if order.paid_amount < target_amount or order.remaining_amount != 0 or order.payment_status != Order.PAYMENT_PAID:
            order.paid_amount = target_amount
            order.remaining_amount = Decimal('0')
            order.payment_status = Order.PAYMENT_PAID
            order.save(update_fields=['paid_amount', 'remaining_amount', 'payment_status'])
        return None

    tx = record_transaction(
        transaction_type=PaymentTransaction.TYPE_CUSTOMER_PAYMENT,
        direction=PaymentTransaction.DIRECTION_IN,
        amount=amount_to_record,
        cash_account=cash_account,
        related_order=order,
        related_customer=order.customer,
        notes=notes or f'قيمة بيع تلقائية للطلب {order.order_number}',
        created_by=user,
    )
    order.paid_amount = target_amount
    order.remaining_amount = Decimal('0')
    order.payment_status = Order.PAYMENT_PAID
    order.save(update_fields=['paid_amount', 'remaining_amount', 'payment_status'])
    return tx


@transaction.atomic
def record_order_refund(*, order, user, cash_account=None, amount=None, notes=''):
    order = order.__class__.objects.select_for_update().get(pk=order.pk)
    incoming = PaymentTransaction.objects.filter(
        related_order=order,
        transaction_type=PaymentTransaction.TYPE_CUSTOMER_PAYMENT,
        direction=PaymentTransaction.DIRECTION_IN,
    ).aggregate(v=Sum('amount'))['v'] or Decimal('0')
    outgoing = PaymentTransaction.objects.filter(
        related_order=order,
        transaction_type=PaymentTransaction.TYPE_REFUND,
        direction=PaymentTransaction.DIRECTION_OUT,
    ).aggregate(v=Sum('amount'))['v'] or Decimal('0')
    refundable = incoming - outgoing
    amount_to_refund = Decimal(str(amount)) if amount is not None else refundable
    amount_to_refund = min(amount_to_refund, refundable)
    if amount_to_refund <= 0:
        return None
    return record_transaction(
        transaction_type=PaymentTransaction.TYPE_REFUND,
        direction=PaymentTransaction.DIRECTION_OUT,
        amount=amount_to_refund,
        cash_account=cash_account,
        related_order=order,
        related_customer=order.customer,
        notes=notes or f'رد تلقائي لإلغاء الطلب {order.order_number}',
        created_by=user,
    )


@transaction.atomic
def collect_order_payment(*, order, amount, user, cash_account=None, notes='', transaction_date=None):
    from orders.models import Order

    amount = _as_decimal(amount)
    order = Order.objects.select_for_update().get(pk=order.pk)
    if amount > order.remaining_amount:
        raise ValidationError('مبلغ التحصيل أكبر من المتبقي على الطلب')
    tx = record_customer_payment(
        order=order,
        customer=order.customer,
        amount=amount,
        user=user,
        cash_account=cash_account,
        notes=notes,
        transaction_date=transaction_date,
    )
    order.paid_amount = F('paid_amount') + amount
    order.save(update_fields=['paid_amount'])
    order.refresh_from_db(fields=['paid_amount'])
    order.remaining_amount = max(order.total - order.paid_amount, Decimal('0'))
    if order.paid_amount <= 0:
        order.payment_status = Order.PAYMENT_UNPAID
    elif order.paid_amount >= order.total:
        order.payment_status = Order.PAYMENT_PAID
    else:
        order.payment_status = Order.PAYMENT_PARTIAL
    order.save(update_fields=['remaining_amount', 'payment_status'])
    return tx


def add_expense(*, amount, cash_account, user, notes='', transaction_date=None):
    return record_transaction(
        transaction_type=PaymentTransaction.TYPE_EXPENSE,
        direction=PaymentTransaction.DIRECTION_OUT,
        amount=amount,
        cash_account=cash_account,
        notes=notes,
        created_by=user,
        transaction_date=transaction_date,
    )


@transaction.atomic
def delete_transaction(*, payment_transaction, user=None):
    tx = PaymentTransaction.objects.select_for_update().select_related('cash_account').get(pk=payment_transaction.pk)
    account = CashAccount.objects.select_for_update().get(pk=tx.cash_account_id)
    old_balance = account.balance
    if tx.direction == PaymentTransaction.DIRECTION_IN:
        if not account.allow_overdraft and account.balance < tx.amount:
            raise ValidationError('لا يمكن حذف حركة داخلة لأن رصيد الخزنة الحالي أقل من مبلغ الحركة')
        account.balance = F('balance') - tx.amount
    elif tx.direction == PaymentTransaction.DIRECTION_OUT:
        account.balance = F('balance') + tx.amount
    else:
        raise ValidationError('اتجاه الحركة المالية غير صحيح')
    account.save(update_fields=['balance'])
    account.refresh_from_db(fields=['balance'])
    tx_repr = str(tx)
    tx_pk = tx.pk
    tx_amount = tx.amount
    tx.delete()

    log_audit(
        user=user,
        action=AuditLog.ACTION_DELETE,
        section=AuditLog.SECTION_FINANCE,
        model_name='PaymentTransaction',
        object_id=tx_pk,
        object_repr=tx_repr,
        changes_before={'account_balance': str(old_balance)},
        changes_after={'account_balance': str(account.balance)},
        notes=f'حذف حركة مالية وعكس أثرها على الخزنة - المبلغ: {tx_amount}',
    )


@transaction.atomic
def transfer_between_accounts(*, from_account, to_account, amount, user, notes='', transaction_date=None):
    if from_account == to_account:
        raise ValidationError('لا يمكن التحويل إلى نفس الخزنة')
    reference = f'TRF-{uuid4().hex[:12].upper()}'
    out_tx = record_transaction(
        transaction_type=PaymentTransaction.TYPE_TRANSFER,
        direction=PaymentTransaction.DIRECTION_OUT,
        amount=amount,
        cash_account=from_account,
        notes=notes,
        created_by=user,
        reference=reference,
        transaction_date=transaction_date,
    )
    in_tx = record_transaction(
        transaction_type=PaymentTransaction.TYPE_TRANSFER,
        direction=PaymentTransaction.DIRECTION_IN,
        amount=amount,
        cash_account=to_account,
        notes=notes,
        created_by=user,
        reference=reference,
        transaction_date=transaction_date,
    )
    return out_tx, in_tx


def record_sales_rep_collection(*, sales_rep, amount, user, cash_account=None, order=None, customer=None, notes='', transaction_date=None):
    return record_transaction(
        transaction_type=PaymentTransaction.TYPE_SALES_REP_COLLECTION,
        direction=PaymentTransaction.DIRECTION_IN,
        amount=amount,
        cash_account=cash_account,
        related_order=order,
        related_customer=customer,
        related_sales_rep=sales_rep,
        notes=notes,
        created_by=user,
        transaction_date=transaction_date,
    )
