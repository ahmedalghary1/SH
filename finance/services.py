from datetime import date, datetime
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


def _money(amount):
    return Decimal(str(amount or 0))


def _locked_account(account):
    account = account or CashAccount.get_default()
    return CashAccount.objects.select_for_update().get(pk=account.pk)


def _sync_order_payment_status(order):
    from orders.models import Order

    order.paid_amount = max(Decimal(str(order.paid_amount or 0)), Decimal('0'))
    order.remaining_amount = max(Decimal(str(order.total or 0)) - order.paid_amount, Decimal('0'))
    if order.remaining_amount <= 0:
        order.payment_status = Order.PAYMENT_PAID
    elif order.paid_amount <= 0:
        order.payment_status = Order.PAYMENT_UNPAID
    else:
        order.payment_status = Order.PAYMENT_PARTIAL
    order.save(update_fields=['paid_amount', 'remaining_amount', 'payment_status'])
    return order


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


@transaction.atomic
def record_customer_payment(*, order, customer, amount, user, cash_account=None, notes='', transaction_date=None):
    from customers.models import Customer

    amount = _as_decimal(amount)
    if order and amount > order.remaining_amount:
        raise ValidationError('مبلغ التحصيل أكبر من المتبقي على الطلب')
    if not order and customer:
        customer = Customer.objects.select_for_update().get(pk=customer.pk)
        if amount > (customer.opening_balance or 0):
            raise ValidationError('مبلغ القبض أكبر من رصيد العميل الافتتاحي')
    tx = record_transaction(
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
    if not order and customer:
        customer.opening_balance = F('opening_balance') - amount
        customer.save(update_fields=['opening_balance'])
    return tx


@transaction.atomic
def collect_customer_balance_payment(*, customer, amount, user, cash_account=None, notes='', transaction_date=None):
    from customers.models import Customer
    from orders.models import Order

    amount = _as_decimal(amount)
    customer = Customer.objects.select_for_update().get(pk=customer.pk)
    remaining_to_allocate = amount
    transactions = []

    if customer.opening_balance and customer.opening_balance > 0:
        opening_payment = min(remaining_to_allocate, Decimal(str(customer.opening_balance)))
        if opening_payment > 0:
            transactions.append(record_customer_payment(
                order=None,
                customer=customer,
                amount=opening_payment,
                user=user,
                cash_account=cash_account,
                notes=notes or 'تحصيل من رصيد افتتاحي',
                transaction_date=transaction_date,
            ))
            remaining_to_allocate -= opening_payment
            customer.refresh_from_db(fields=['opening_balance'])

    open_orders = Order.objects.select_for_update().filter(
        customer=customer,
        remaining_amount__gt=0,
    ).exclude(
        status__in=[Order.STATUS_DRAFT, Order.STATUS_CANCELLED, Order.STATUS_RETURNED],
    ).order_by('created_at', 'pk')
    for order in open_orders:
        if remaining_to_allocate <= 0:
            break
        order_payment = min(remaining_to_allocate, Decimal(str(order.remaining_amount or 0)))
        if order_payment <= 0:
            continue
        transactions.append(collect_order_payment(
            order=order,
            amount=order_payment,
            user=user,
            cash_account=cash_account,
            notes=notes or f'تحصيل من العميل {customer}',
            transaction_date=transaction_date,
        ))
        remaining_to_allocate -= order_payment

    if remaining_to_allocate > 0:
        raise ValidationError('مبلغ التحصيل أكبر من مديونية العميل')
    return transactions


@transaction.atomic
def record_customer_refund_payment(*, customer, amount, user, cash_account=None, order=None, notes='', transaction_date=None):
    from customers.models import Customer

    amount = _as_decimal(amount)
    if customer:
        customer = Customer.objects.select_for_update().get(pk=customer.pk)
    tx = record_transaction(
        transaction_type=PaymentTransaction.TYPE_REFUND,
        direction=PaymentTransaction.DIRECTION_OUT,
        amount=amount,
        cash_account=cash_account,
        related_order=order,
        related_customer=customer,
        notes=notes,
        created_by=user,
        transaction_date=transaction_date,
    )
    if customer and not order:
        Customer.objects.filter(pk=customer.pk).update(opening_balance=F('opening_balance') + amount)
    return tx


def record_customer_allowed_discount(*, customer, amount, user, order=None, cash_account=None, notes='', transaction_date=None):
    amount = _as_decimal(amount)
    return PaymentTransaction.objects.create(
        transaction_type=PaymentTransaction.TYPE_CUSTOMER_ALLOWED_DISCOUNT,
        direction=PaymentTransaction.DIRECTION_OUT,
        amount=amount,
        cash_account=cash_account or CashAccount.get_cash_drawer(),
        related_order=order,
        related_customer=customer,
        notes=notes,
        transaction_date=transaction_date or timezone.localdate(),
        created_by=user,
        affects_cash=False,
    )


def _statement_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return timezone.localdate()


def _statement_entry(*, date_value, sort_at, sort_order, entry_type, description, debit=0, credit=0, **extra):
    entry = {
        'date': _statement_date(date_value),
        'sort_at': sort_at or timezone.now(),
        'sort_order': sort_order,
        'type': entry_type,
        'description': description,
        'debit': _money(debit),
        'credit': _money(credit),
    }
    entry.update(extra)
    return entry


def _customer_statement_orders(customer):
    from orders.models import Order

    return Order.objects.filter(customer=customer).exclude(
        status__in=[Order.STATUS_DRAFT, Order.STATUS_CANCELLED],
    ).exclude(
        document_type=Order.DOCUMENT_QUOTE,
    )


def build_customer_statement(customer):
    from returns.models import SalesReturn

    orders = _customer_statement_orders(customer).select_related('created_by').order_by('created_at', 'pk')
    transactions = PaymentTransaction.objects.filter(
        related_customer=customer,
        transaction_type__in=[
            PaymentTransaction.TYPE_CUSTOMER_PAYMENT,
            PaymentTransaction.TYPE_SALES_REP_COLLECTION,
            PaymentTransaction.TYPE_REFUND,
            PaymentTransaction.TYPE_CUSTOMER_ALLOWED_DISCOUNT,
        ],
    ).select_related('cash_account', 'related_order', 'created_by').order_by('transaction_date', 'created_at', 'pk')
    returns = SalesReturn.objects.filter(
        customer=customer,
        status=SalesReturn.STATUS_COMPLETED,
    ).select_related('order').prefetch_related('exchange_items').order_by('created_at', 'pk')

    entries = []
    for order in orders:
        amount = _money(order.total)
        if amount <= 0:
            continue
        entries.append(_statement_entry(
            date_value=order.created_at,
            sort_at=order.created_at,
            sort_order=10,
            entry_type='فاتورة بيع',
            description=f'فاتورة {order.order_number}',
            debit=amount,
            order=order,
        ))

    for sales_return in returns:
        if sales_return.return_type == SalesReturn.TYPE_EXCHANGE:
            for exchange in sales_return.exchange_items.all():
                difference = _money(exchange.price_difference)
                if difference > 0:
                    entries.append(_statement_entry(
                        date_value=sales_return.created_at,
                        sort_at=sales_return.created_at,
                        sort_order=20,
                        entry_type='فرق استبدال',
                        description=f'فرق استبدال على {sales_return.order.order_number}',
                        debit=difference,
                        sales_return=sales_return,
                    ))
                elif difference < 0:
                    entries.append(_statement_entry(
                        date_value=sales_return.created_at,
                        sort_at=sales_return.created_at,
                        sort_order=20,
                        entry_type='فرق استبدال',
                        description=f'فرق استبدال لصالح العميل على {sales_return.order.order_number}',
                        credit=abs(difference),
                        sales_return=sales_return,
                    ))
            continue

        refund_amount = _money(sales_return.refund_amount)
        if refund_amount <= 0:
            continue
        entries.append(_statement_entry(
            date_value=sales_return.created_at,
            sort_at=sales_return.created_at,
            sort_order=20,
            entry_type='مرتجع',
            description=f'مرتجع {sales_return.pk} على {sales_return.order.order_number}',
            credit=refund_amount,
            sales_return=sales_return,
        ))

    for tx in transactions:
        amount = _money(tx.amount)
        if amount <= 0:
            continue
        description = tx.notes or tx.get_transaction_type_display()
        if tx.related_order_id and not tx.notes:
            description = f'{description} - {tx.related_order.order_number}'

        if (
            tx.transaction_type in [PaymentTransaction.TYPE_CUSTOMER_PAYMENT, PaymentTransaction.TYPE_SALES_REP_COLLECTION]
            and tx.direction == PaymentTransaction.DIRECTION_IN
        ):
            entries.append(_statement_entry(
                date_value=tx.transaction_date,
                sort_at=tx.created_at,
                sort_order=30,
                entry_type=tx.get_transaction_type_display(),
                description=description,
                credit=amount,
                payment=tx,
            ))
        elif tx.transaction_type == PaymentTransaction.TYPE_REFUND and tx.direction == PaymentTransaction.DIRECTION_OUT:
            entries.append(_statement_entry(
                date_value=tx.transaction_date,
                sort_at=tx.created_at,
                sort_order=40,
                entry_type=tx.get_transaction_type_display(),
                description=description,
                debit=amount,
                payment=tx,
            ))
        elif tx.transaction_type == PaymentTransaction.TYPE_CUSTOMER_ALLOWED_DISCOUNT:
            entries.append(_statement_entry(
                date_value=tx.transaction_date,
                sort_at=tx.created_at,
                sort_order=35,
                entry_type=tx.get_transaction_type_display(),
                description=description,
                credit=amount,
                payment=tx,
            ))

    orders_balance = orders.aggregate(v=Sum('remaining_amount'))['v'] or Decimal('0')
    target_balance = _money(customer.opening_balance) + _money(orders_balance)
    movement_balance = sum((entry['debit'] - entry['credit'] for entry in entries), Decimal('0'))
    statement_opening_balance = target_balance - movement_balance
    if statement_opening_balance:
        opening_date = _statement_date(getattr(customer, 'created_at', None))
        if entries:
            opening_date = min([opening_date] + [entry['date'] for entry in entries])
        entries.append(_statement_entry(
            date_value=opening_date,
            sort_at=getattr(customer, 'created_at', None),
            sort_order=0,
            entry_type='رصيد سابق',
            description='رصيد سابق',
            debit=statement_opening_balance if statement_opening_balance > 0 else 0,
            credit=abs(statement_opening_balance) if statement_opening_balance < 0 else 0,
        ))

    entries.sort(key=lambda entry: (entry['date'], entry['sort_order'], entry['sort_at'], entry.get('payment').pk if entry.get('payment') else 0))

    balance = Decimal('0')
    total_debit = Decimal('0')
    total_credit = Decimal('0')
    for entry in entries:
        total_debit += entry['debit']
        total_credit += entry['credit']
        balance += entry['debit'] - entry['credit']
        entry['balance'] = balance

    return {
        'entries': entries,
        'total_debit': total_debit,
        'total_credit': total_credit,
        'current_balance': balance,
        'orders_balance': orders_balance,
        'statement_opening_balance': statement_opening_balance,
        'remaining_opening_balance': _money(customer.opening_balance),
        'opening_balance': _money(customer.opening_balance),
    }


def build_cash_account_statement(account):
    transactions = PaymentTransaction.objects.filter(
        cash_account=account,
    ).select_related(
        'related_order',
        'related_customer',
        'related_sales_rep',
        'related_supplier',
        'created_by',
    ).order_by('transaction_date', 'created_at', 'pk')

    entries = []
    total_in = Decimal('0')
    total_out = Decimal('0')
    movement_total = Decimal('0')
    non_cash_transactions_count = 0

    for tx in transactions:
        amount = _money(tx.amount)
        affects_cash = getattr(tx, 'affects_cash', True)
        balance_delta = Decimal('0')
        in_amount = Decimal('0')
        out_amount = Decimal('0')

        if tx.direction == PaymentTransaction.DIRECTION_IN:
            in_amount = amount
            if affects_cash:
                balance_delta = amount
                total_in += amount
        elif tx.direction == PaymentTransaction.DIRECTION_OUT:
            out_amount = amount
            if affects_cash:
                balance_delta = -amount
                total_out += amount

        if not affects_cash:
            non_cash_transactions_count += 1

        movement_total += balance_delta
        entries.append({
            'date': _statement_date(tx.transaction_date),
            'created_at': tx.created_at,
            'type': tx.get_transaction_type_display(),
            'direction': tx.get_direction_display(),
            'description': tx.notes or tx.get_transaction_type_display(),
            'in_amount': in_amount,
            'out_amount': out_amount,
            'balance_delta': balance_delta,
            'affects_cash': affects_cash,
            'order': tx.related_order,
            'customer': tx.related_customer,
            'supplier': tx.related_supplier or tx.related_supplier_name,
            'sales_rep': tx.related_sales_rep,
            'reference': tx.reference,
            'created_by': tx.created_by,
        })

    opening_balance = _money(account.balance) - movement_total
    running_balance = opening_balance
    for entry in entries:
        running_balance += entry['balance_delta']
        entry['balance'] = running_balance

    return {
        'entries': entries,
        'opening_balance': opening_balance,
        'current_balance': _money(account.balance),
        'total_in': total_in,
        'total_out': total_out,
        'net_movement': total_in - total_out,
        'transactions_count': len(entries),
        'non_cash_transactions_count': non_cash_transactions_count,
    }


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

    account = cash_account or CashAccount.get_for_user(user)
    tx = record_transaction(
        transaction_type=PaymentTransaction.TYPE_CUSTOMER_PAYMENT,
        direction=PaymentTransaction.DIRECTION_IN,
        amount=amount_to_record,
        cash_account=account,
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
    from customers.models import Customer

    order = Order.objects.select_for_update().get(pk=order.pk)
    amount = Decimal(str(amount or 0))
    if amount == 0:
        raise ValidationError('مبلغ التحصيل لا يمكن أن يساوي صفر')
    if amount < 0:
        refund_amount = abs(amount)
        current_paid = Decimal(str(order.paid_amount or 0))
        paid_reversal = min(refund_amount, current_paid)
        extra_customer_balance = refund_amount - paid_reversal
        tx = record_customer_refund_payment(
            order=order,
            customer=order.customer,
            amount=refund_amount,
            user=user,
            cash_account=cash_account,
            notes=notes,
            transaction_date=transaction_date,
        )
        order.paid_amount = current_paid - paid_reversal
        order.save(update_fields=['paid_amount'])
        _sync_order_payment_status(order)
        if extra_customer_balance > 0 and order.customer_id:
            Customer.objects.filter(pk=order.customer_id).update(opening_balance=F('opening_balance') + extra_customer_balance)
        return tx
    amount = _as_decimal(amount)
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
    _sync_order_payment_status(order)
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
    affects_cash = getattr(tx, 'affects_cash', True)
    if not affects_cash:
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
            notes=f'Ø­Ø°Ù Ø­Ø±ÙƒØ© Ù…Ø§Ù„ÙŠØ© - Ø§Ù„Ù…Ø¨Ù„Øº: {tx_amount}',
        )
        return
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
    if (
        tx.transaction_type == PaymentTransaction.TYPE_CUSTOMER_PAYMENT
        and tx.direction == PaymentTransaction.DIRECTION_IN
        and tx.related_customer_id
        and not tx.related_order_id
    ):
        from customers.models import Customer

        Customer.objects.filter(pk=tx.related_customer_id).update(opening_balance=F('opening_balance') + tx.amount)
    if (
        tx.transaction_type == PaymentTransaction.TYPE_REFUND
        and tx.direction == PaymentTransaction.DIRECTION_OUT
        and tx.related_customer_id
        and not tx.related_order_id
    ):
        from customers.models import Customer

        Customer.objects.filter(pk=tx.related_customer_id).update(opening_balance=F('opening_balance') - tx.amount)
    if (
        tx.transaction_type == PaymentTransaction.TYPE_CUSTOMER_PAYMENT
        and tx.direction == PaymentTransaction.DIRECTION_IN
        and tx.related_order_id
    ):
        from orders.models import Order

        order = Order.objects.select_for_update().get(pk=tx.related_order_id)
        order.paid_amount = max(Decimal(str(order.paid_amount or 0)) - tx.amount, Decimal('0'))
        _sync_order_payment_status(order)
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


@transaction.atomic
def record_sales_rep_collection(*, sales_rep, amount, user, cash_account=None, order=None, customer=None, notes='', transaction_date=None):
    amount = Decimal(str(amount or 0))
    if amount == 0:
        raise ValidationError('مبلغ التحصيل لا يمكن أن يساوي صفر')
    if amount < 0:
        refund_amount = abs(amount)
        if order:
            from orders.models import Order

            order = Order.objects.select_for_update().get(pk=order.pk)
            customer = customer or order.customer
        tx = record_transaction(
            transaction_type=PaymentTransaction.TYPE_REFUND,
            direction=PaymentTransaction.DIRECTION_OUT,
            amount=refund_amount,
            cash_account=cash_account,
            related_order=order,
            related_customer=customer,
            related_sales_rep=sales_rep,
            notes=notes,
            created_by=user,
            transaction_date=transaction_date,
        )
        if order:
            from customers.models import Customer

            current_paid = Decimal(str(order.paid_amount or 0))
            paid_reversal = min(refund_amount, current_paid)
            extra_customer_balance = refund_amount - paid_reversal
            order.paid_amount = current_paid - paid_reversal
            order.save(update_fields=['paid_amount'])
            _sync_order_payment_status(order)
            if extra_customer_balance > 0 and order.customer_id:
                Customer.objects.filter(pk=order.customer_id).update(opening_balance=F('opening_balance') + extra_customer_balance)
        elif customer:
            from customers.models import Customer

            Customer.objects.filter(pk=customer.pk).update(opening_balance=F('opening_balance') + refund_amount)
        return tx
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
