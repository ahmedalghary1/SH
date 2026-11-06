"""Convert unpaid cash refunds to customer account settlements, with an audit trail."""

import hashlib
import json
from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction

from audit.models import AuditLog
from audit.services import log_audit
from finance.models import CashAccount, PaymentTransaction
from finance.reconciliation import (
    assert_order_return_balance,
    inspect_order_return_balance,
)
from finance.services import (
    build_customer_statement,
    collect_order_payment,
    record_customer_payment,
    record_transaction,
)
from orders.models import Order

from .models import ReturnAccountSettlement, SalesReturn
from .services import _in_return_branch


def has_active_return_settlement(order):
    return PaymentTransaction.objects.filter(
        related_order=order, return_account_settlements__sales_return__status=SalesReturn.STATUS_COMPLETED,
    ).exists()


def allocate_return_credit(settlement, *, user, cash_account):
    sales_return = settlement.sales_return
    if not sales_return.customer_id:
        raise ValidationError('تسوية المرتجع على الحساب تتطلب عميلًا مسجلًا')
    remaining = settlement.amount
    orders = Order.objects.filter(customer_id=sales_return.customer_id, branch_id=sales_return.branch_id,
                                  document_type=Order.DOCUMENT_SALE, remaining_amount__gt=0).exclude(
        pk=sales_return.order_id,
    ).exclude(status__in=[Order.STATUS_DRAFT, Order.STATUS_CANCELLED, Order.STATUS_RETURNED]).order_by('created_at', 'pk')
    for order in orders:
        if remaining <= 0:
            break
        assert_order_return_balance(order)
        amount = min(remaining, order.remaining_amount)
        payment = collect_order_payment(order=order, amount=amount, user=user, cash_account=cash_account,
                                        affects_cash=False, notes=f'تسوية من المرتجع #{sales_return.pk}',
                                        transaction_date=sales_return.created_at)
        settlement.allocations.add(payment)
        remaining -= amount
    if remaining > 0:
        payment = record_customer_payment(order=None, customer=sales_return.customer, amount=remaining,
                                          user=user, cash_account=cash_account, affects_cash=False,
                                          notes=f'رصيد من المرتجع #{sales_return.pk}',
                                          transaction_date=sales_return.created_at)
        settlement.allocations.add(payment)


def reverse_return_credit(settlement, *, user):
    # New reversal rows preserve the original entries without counting them in
    # the statement twice; the return itself is the credit shown to the customer.
    for payment in list(settlement.allocations.select_related('cash_account').order_by('pk')):
        if payment.direction != PaymentTransaction.DIRECTION_IN:
            raise ValidationError('تسوية المرتجع تحتوي على عكس سابق يحتاج مراجعة')
        order = None
        if payment.related_order_id:
            order = Order.objects.select_for_update().get(pk=payment.related_order_id)
            if (order.status in {Order.STATUS_DRAFT, Order.STATUS_CANCELLED, Order.STATUS_RETURNED}
                    or order.sales_returns.filter(status=SalesReturn.STATUS_COMPLETED).exists()
                    or order.paid_amount < payment.amount):
                raise ValidationError('توجد عمليات لاحقة على فاتورة سُددت من المرتجع. راجعها قبل إلغاء التسوية')
            assert_order_return_balance(order)
            order.paid_amount -= payment.amount
            order.remaining_amount += payment.amount
            order.payment_status = Order.PAYMENT_PARTIAL if order.paid_amount > 0 else Order.PAYMENT_UNPAID
            order.save(update_fields=['paid_amount', 'remaining_amount', 'payment_status'])
        reversal = record_transaction(
            transaction_type=PaymentTransaction.TYPE_REFUND, direction=PaymentTransaction.DIRECTION_OUT,
            amount=payment.amount, cash_account=payment.cash_account, related_order=order,
            related_customer=settlement.sales_return.customer, affects_cash=False,
            affects_customer_balance=payment.affects_customer_balance, created_by=user,
            notes=f'عكس تسوية المرتجع #{settlement.sales_return_id}',
        )
        settlement.allocations.add(reversal)


def refund_account_review(sales_return):
    if (sales_return.status != SalesReturn.STATUS_COMPLETED or sales_return.return_type == SalesReturn.TYPE_EXCHANGE
            or not sales_return.customer_id):
        raise ValidationError('هذه المعالجة متاحة لمرتجع مكتمل لعميل مسجل، وليست متاحة للاستبدال')
    if ReturnAccountSettlement.objects.filter(sales_return=sales_return).exists():
        raise ValidationError('تمت تسوية هذا المرتجع على حساب العميل بالفعل')
    order = sales_return.order
    assert_order_return_balance(order)
    effects = defaultdict(lambda: Decimal(0))
    payments = list(sales_return.financial_transactions.order_by('pk'))
    for payment in payments:
        if (payment.related_order_id != order.pk or payment.branch_id != order.branch_id
                or payment.affects_customer_balance or not payment.affects_cash):
            raise ValidationError('الحركات المرتبطة بالمرتجع تحتاج مراجعة قبل التحويل')
        effects[payment.cash_account_id] += payment.amount if payment.direction == PaymentTransaction.DIRECTION_IN else -payment.amount
    amount = -sum(effects.values(), Decimal(0))
    if amount <= 0 or amount != sales_return.refund_amount - sales_return.debt_reduction:
        raise ValidationError('لا يوجد استرداد نقدي متطابق يمكن تحويله إلى حساب العميل')
    states = [inspect_order_return_balance(item) for item in Order.objects.filter(
        customer_id=sales_return.customer_id, branch_id=sales_return.branch_id,
        document_type=Order.DOCUMENT_SALE,
    ).exclude(status__in=[Order.STATUS_DRAFT, Order.STATUS_CANCELLED]).order_by('pk')]
    balance = build_customer_statement(sales_return.customer)['current_balance']
    snapshot = {'return': sales_return.pk, 'revision': sales_return.revision,
                'orders': [(row['order_id'], row['fingerprint']) for row in states],
                'balance': balance, 'cash': sorted(effects.items()), 'amount': amount}
    fingerprint = hashlib.sha256(json.dumps(snapshot, cls=DjangoJSONEncoder, sort_keys=True).encode()).hexdigest()
    return {'return_id': sales_return.pk, 'customer_id': sales_return.customer_id, 'branch_id': sales_return.branch_id,
            'revision': sales_return.revision, 'amount': str(amount), 'balance_before': str(balance),
            'balance_after': str(balance - amount), 'fingerprint': fingerprint}


@transaction.atomic
@_in_return_branch
def convert_unpaid_refund_to_account(*, sales_return, user, fingerprint, reason):
    if (not user.is_active or not user.is_manager
            or (not user.is_superuser and user.branch_id != sales_return.branch_id)):
        raise ValidationError('لا تملك صلاحية تصحيح الاسترداد في هذا الفرع')
    sales_return = SalesReturn.objects.select_for_update().get(pk=sales_return.pk)
    if ReturnAccountSettlement.objects.filter(sales_return=sales_return).exists():
        return sales_return
    if not sales_return.customer_id:
        raise ValidationError('تسوية المرتجع تتطلب حساب عميل مسجل')
    list(Order.objects.select_for_update().filter(customer_id=sales_return.customer_id).order_by('pk'))
    review = refund_account_review(sales_return)
    if review['fingerprint'] != fingerprint:
        raise ValidationError('تغيرت بيانات الحساب بعد المراجعة. أعد فتح المعالجة قبل التنفيذ')
    effects = defaultdict(lambda: Decimal(0))
    for payment in sales_return.financial_transactions.select_for_update().all():
        effects[payment.cash_account_id] += payment.amount if payment.direction == PaymentTransaction.DIRECTION_IN else -payment.amount
    accounts = {account.pk: account for account in CashAccount.objects.select_for_update().filter(pk__in=effects).order_by('pk')}
    for account_id, effect in sorted(effects.items()):
        if effect:
            correction = record_transaction(
                transaction_type=PaymentTransaction.TYPE_ADJUSTMENT,
                direction=PaymentTransaction.DIRECTION_IN if effect < 0 else PaymentTransaction.DIRECTION_OUT,
                amount=abs(effect), cash_account=accounts[account_id], related_order=sales_return.order,
                related_customer=sales_return.customer, created_by=user,
                notes=f'تصحيح استرداد غير منفذ للمرتجع #{sales_return.pk}: {reason}',
            )
            sales_return.financial_transactions.add(correction)
    settlement = ReturnAccountSettlement.objects.create(
        branch_id=sales_return.branch_id, sales_return=sales_return, amount=Decimal(review['amount']),
        created_by=user, reason=reason,
    )
    allocate_return_credit(settlement, user=user, cash_account=accounts[min(accounts)])
    sales_return.revision += 1
    sales_return.save(update_fields=['revision'])
    log_audit(user=user, action=AuditLog.ACTION_UPDATE, section=AuditLog.SECTION_RETURNS,
              model_name='SalesReturn', object_id=sales_return.pk, object_repr=str(sales_return),
              changes_before={'cash_refund': review['amount'], 'customer_balance': review['balance_before']},
              changes_after={'cash_refund': '0.00', 'customer_balance': review['balance_after']},
              notes=f'تحويل استرداد غير منفذ إلى حساب العميل: {reason}', branch=sales_return.branch_id)
    return sales_return
