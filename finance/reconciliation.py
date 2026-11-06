"""Inspect legacy return balances without inventing receipts or moving cash."""

import hashlib
import json
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Sum

from .models import PaymentTransaction


def expected_order_remaining(order):
    from returns.models import SalesReturn

    reduction = SalesReturn.all_objects.filter(
        order_id=order.pk, branch_id=order.branch_id, status=SalesReturn.STATUS_COMPLETED,
    ).exclude(return_type=SalesReturn.TYPE_EXCHANGE).aggregate(value=Sum('debt_reduction'))['value'] or Decimal(0)
    # A negative result indicates an unresolved overcollection, not a safe zero.
    return order.total - order.paid_amount - reduction


def assert_order_return_balance(order):
    expected = expected_order_remaining(order)
    if expected < 0:
        raise ValidationError('رصيد الفاتورة غير متطابق: المدفوع وتخفيض المرتجعات يتجاوزان إجمالي الفاتورة. يجب مراجعتها أولًا')
    if order.remaining_amount != expected:
        raise ValidationError(
            f'رصيد الفاتورة غير متطابق: المسجل {order.remaining_amount:.2f} والمتوقع {expected:.2f}. '
            'يجب مراجعة الفاتورة وتصحيح رصيدها قبل تعديل المرتجع أو إلغائه'
        )


def inspect_order_return_balance(order):
    from orders.models import Order
    from returns.models import ReturnAccountSettlement, SalesReturn

    problems = []
    returns = list(SalesReturn.all_objects.filter(order_id=order.pk).order_by('pk').prefetch_related(
        'financial_transactions__sales_returns', 'items', 'exchange_items',
    ))
    payments = list(PaymentTransaction.all_objects.filter(related_order_id=order.pk).order_by('pk'))
    linked_ids = set()
    return_data = []
    debt = Decimal(0)
    for sales_return in returns:
        settlement = ReturnAccountSettlement.objects.filter(sales_return=sales_return).prefetch_related('allocations').first()
        linked = sorted(sales_return.financial_transactions.all(), key=lambda payment: payment.pk)
        linked_ids.update(payment.pk for payment in linked)
        items = sorted(sales_return.items.all(), key=lambda item: item.pk)
        exchanges = sorted(sales_return.exchange_items.all(), key=lambda item: item.pk)
        if sales_return.branch_id != order.branch_id:
            problems.append(f'return_{sales_return.pk}:wrong_branch')
        if linked and sales_return.status not in {SalesReturn.STATUS_COMPLETED, SalesReturn.STATUS_CANCELLED}:
            problems.append(f'return_{sales_return.pk}:unexpected_payment_links')
        if sales_return.status in {SalesReturn.STATUS_COMPLETED, SalesReturn.STATUS_CANCELLED}:
            if sum((item.refund_amount for item in items), Decimal(0)) != sales_return.refund_amount:
                problems.append(f'return_{sales_return.pk}:item_total_mismatch')
            if not Decimal(0) <= sales_return.debt_reduction <= sales_return.refund_amount:
                problems.append(f'return_{sales_return.pk}:invalid_debt_reduction')
            for payment in linked:
                if (payment.related_order_id != order.pk or payment.branch_id != order.branch_id
                        or payment.related_customer_id not in (None, order.customer_id)
                        or payment.affects_customer_balance or not payment.affects_cash
                        or len(payment.sales_returns.all()) != 1):
                    problems.append(f'return_{sales_return.pk}:invalid_payment_link')
            cash_net = sum((payment.amount if payment.direction == PaymentTransaction.DIRECTION_IN else -payment.amount
                            for payment in linked if payment.affects_cash), Decimal(0))
            expected_cash = Decimal(0)
            if sales_return.status == SalesReturn.STATUS_COMPLETED:
                if sales_return.return_type == SalesReturn.TYPE_EXCHANGE:
                    expected_cash = sum((item.price_difference for item in exchanges), Decimal(0))
                else:
                    debt += sales_return.debt_reduction
                    expected_cash = sales_return.debt_reduction - sales_return.refund_amount + (
                        settlement.amount if settlement else Decimal(0))
            if cash_net != expected_cash:
                problems.append(f'return_{sales_return.pk}:cash_links_mismatch')
            if settlement:
                allocated = sum((payment.amount if payment.direction == PaymentTransaction.DIRECTION_IN else -payment.amount
                                 for payment in settlement.allocations.all()), Decimal(0))
                expected_allocated = settlement.amount if sales_return.status == SalesReturn.STATUS_COMPLETED else Decimal(0)
                if allocated != expected_allocated:
                    problems.append(f'return_{sales_return.pk}:account_settlement_mismatch')
        return_data.append({
            'id': sales_return.pk, 'branch': sales_return.branch_id, 'status': sales_return.status,
            'type': sales_return.return_type, 'revision': sales_return.revision,
            'refund': sales_return.refund_amount, 'debt': sales_return.debt_reduction,
            'payments': [(p.pk, p.amount, p.direction, p.cash_account_id, p.related_order_id,
                          p.branch_id, p.affects_cash, p.affects_customer_balance,
                          sorted(item.pk for item in p.sales_returns.all())) for p in linked],
            'items': [(item.pk, item.quantity, item.refund_amount) for item in items],
            'exchanges': [(item.pk, item.quantity, item.price_difference) for item in exchanges],
            'settlement': None if not settlement else {
                'amount': settlement.amount,
                'allocations': sorted((payment.pk, payment.related_order_id or 0, payment.amount, payment.direction)
                                      for payment in settlement.allocations.all()),
            },
        })

    paid_from_ledger = Decimal(0)
    for payment in payments:
        if payment.pk in linked_ids:
            continue
        if payment.branch_id != order.branch_id:
            problems.append(f'payment_{payment.pk}:wrong_branch')
        if payment.related_customer_id not in (None, order.customer_id):
            problems.append(f'payment_{payment.pk}:wrong_customer')
        if payment.affects_customer_balance:
            # Customer-level adjustments are accounted for outside this invoice.
            continue
        if (payment.transaction_type in {PaymentTransaction.TYPE_CUSTOMER_PAYMENT, PaymentTransaction.TYPE_SALES_REP_COLLECTION}
                and payment.direction == PaymentTransaction.DIRECTION_IN):
            paid_from_ledger += payment.amount
        elif payment.transaction_type == PaymentTransaction.TYPE_REFUND and payment.direction == PaymentTransaction.DIRECTION_OUT:
            paid_from_ledger -= payment.amount
        else:
            problems.append(f'payment_{payment.pk}:unclassified_invoice_movement')
    if paid_from_ledger != order.paid_amount:
        problems.append('paid_amount_does_not_match_receipts')
    raw_remaining = order.total - order.paid_amount - debt
    if raw_remaining < 0:
        problems.append('paid_and_return_credit_exceed_invoice_total')
    expected = max(raw_remaining, Decimal(0))
    payment_status = (Order.PAYMENT_PAID if expected <= 0 else
                      Order.PAYMENT_PARTIAL if order.paid_amount > 0 else Order.PAYMENT_UNPAID)
    snapshot = {
        'order': (order.pk, order.branch_id, order.customer_id, order.document_type, order.status,
                  order.total, order.paid_amount, order.remaining_amount, order.payment_status),
        'returns': return_data,
        'payments': [(p.pk, p.transaction_type, p.direction, p.amount, p.cash_account_id,
                      p.related_customer_id, p.branch_id, p.affects_cash, p.affects_customer_balance) for p in payments],
    }
    fingerprint = hashlib.sha256(json.dumps(snapshot, cls=DjangoJSONEncoder, sort_keys=True).encode()).hexdigest()
    return {
        'order_id': order.pk, 'order_number': order.order_number,
        'paid_stored': str(order.paid_amount), 'paid_verified': str(paid_from_ledger),
        'return_debt': str(debt), 'remaining_before': str(order.remaining_amount),
        'remaining_expected': str(expected), 'payment_status_before': order.payment_status,
        'payment_status_expected': payment_status,
        'needs_repair': order.remaining_amount != expected or order.payment_status != payment_status,
        'problems': sorted(set(problems)), 'fingerprint': fingerprint,
    }


def customer_return_orders(customer):
    from orders.models import Order
    from returns.models import SalesReturn

    return Order.objects.filter(
        customer=customer, branch_id=customer.branch_id, document_type=Order.DOCUMENT_SALE,
        pk__in=SalesReturn.objects.filter(branch_id=customer.branch_id).values('order_id'),
    ).exclude(status__in=[Order.STATUS_DRAFT, Order.STATUS_CANCELLED])


def build_customer_return_review(customer, order_ids=None):
    from .services import build_customer_statement

    orders = customer_return_orders(customer)
    if order_ids:
        orders = orders.filter(pk__in=order_ids)
    rows = [inspect_order_return_balance(order) for order in orders.order_by('pk')]
    balance = build_customer_statement(customer)['current_balance']
    delta = sum((Decimal(row['remaining_expected']) - Decimal(row['remaining_before'])
                 for row in rows if not row['problems']), Decimal(0))
    return {'version': 1, 'customer_id': customer.pk, 'branch_id': customer.branch_id,
            'balance_before': str(balance), 'balance_after_verified_repairs': str(balance + delta), 'orders': rows}


@transaction.atomic
def apply_customer_return_review(*, customer, actor, report, order_ids):
    from audit.models import AuditLog
    from audit.services import log_audit

    if (not isinstance(report, dict) or report.get('version') != 1 or report.get('customer_id') != customer.pk
            or report.get('branch_id') != customer.branch_id or not isinstance(report.get('orders'), list)):
        raise ValidationError('Report does not match the customer and branch.', code='invalid_report')
    if any(not isinstance(row, dict) or type(row.get('order_id')) is not int
           or not isinstance(row.get('fingerprint'), str) for row in report['orders']):
        raise ValidationError('Invalid order entries in the review report.', code='invalid_report')
    if (actor is None or not actor.is_active or not actor.is_manager
            or (not actor.is_superuser and actor.branch_id != customer.branch_id)):
        raise ValidationError('Actor must be an active manager for this branch, or a superuser.', code='invalid_actor')
    reviewed = {row['order_id']: row for row in report['orders']}
    if len(reviewed) != len(report['orders']):
        raise ValidationError('Duplicate orders in the review report.', code='invalid_report')
    if not order_ids or any(type(pk) is not int for pk in order_ids):
        raise ValidationError('Select at least one invoice from this review.', code='invalid_selection')
    selected = sorted(set(order_ids))
    orders = list(customer_return_orders(customer).filter(pk__in=selected).order_by('pk').select_for_update())
    if [order.pk for order in orders] != selected or any(pk not in reviewed for pk in selected):
        raise ValidationError('Every selected order must belong to this customer and appear in the review report.', code='invalid_selection')
    changes = []
    for order in orders:
        current = inspect_order_return_balance(order)
        if current['fingerprint'] != reviewed[order.pk]['fingerprint']:
            raise ValidationError(
                f'Order {order.pk} changed after review. Generate a fresh report; nothing was applied.', code='stale_review',
            )
        if current['problems']:
            raise ValidationError(f"Order {order.pk} requires manual review: {', '.join(current['problems'])}", code='manual_review')
        if current['needs_repair']:
            changes.append((order, current))
    for order, current in changes:
        order.remaining_amount = Decimal(current['remaining_expected'])
        order.payment_status = current['payment_status_expected']
        order.save(update_fields=['remaining_amount', 'payment_status'])
        log_audit(user=actor, action=AuditLog.ACTION_UPDATE, section=AuditLog.SECTION_FINANCE,
                  model_name='Order', object_id=order.pk, object_repr=str(order),
                  changes_before={'remaining_amount': current['remaining_before'],
                                  'payment_status': current['payment_status_before']},
                  changes_after={'remaining_amount': str(order.remaining_amount), 'payment_status': order.payment_status},
                  notes='Verified legacy return balance reconciliation', branch=customer.branch_id)
    return len(changes)
