from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from accounts.models import Branch
from accounts.permissions import can_hard_delete
from audit.models import AuditLog
from audit.services import log_audit
from finance.models import PaymentTransaction
from finance.services import record_order_sale_payment
from orders.models import Order
from settings_app.models import CompanySettings

from .models import Invoice


def invoice_deletion_block_reason(order):
    if order.status == Order.STATUS_CANCELLED:
        return 'هذه الفاتورة محذوفة بالفعل'
    if order.status not in {Order.STATUS_CONFIRMED, Order.STATUS_PREPARING, Order.STATUS_READY, Order.STATUS_COMPLETED}:
        return 'حالة الفاتورة الحالية لا تسمح بالحذف'
    if order.sales_returns.exclude(status='rejected').exists():
        return 'الفاتورة مرتبطة بمرتجع؛ راجع المرتجع أولًا قبل الحذف'
    if order.sales_rep_collections.filter(handed_over_amount__gt=0).exists():
        return 'تم تسليم تحصيلات هذه الفاتورة من عهدة المندوب؛ يجب تسوية العهدة أولًا'
    if order.sales_rep_collections.filter(amount__lt=0).exists():
        return 'الفاتورة مرتبطة برد تحصيل من عهدة مندوب؛ راجع تسوية العهدة أولًا'
    return ''


@transaction.atomic
def delete_invoice(*, invoice, user):
    """Reverse the invoice atomically, retaining original records for audit."""
    from django.core.exceptions import PermissionDenied
    from finance.services import record_customer_balance_adjustment
    from orders.services import cancel_order

    if not can_hard_delete(user):
        raise PermissionDenied('ليس لديك صلاحية حذف الفاتورة')
    order = Order.objects.select_for_update().get(pk=invoice.order_id)
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk, order=order)
    # A repeated POST never returns stock or cash twice.
    if order.status == Order.STATUS_CANCELLED:
        return invoice
    collections = list(order.sales_rep_collections.select_for_update().order_by('pk'))
    reason = invoice_deletion_block_reason(order)
    if reason:
        raise ValidationError(reason)

    old_remaining = str(order.remaining_amount)
    old_status = order.status
    ledger_movements = list(PaymentTransaction.objects.select_for_update().filter(
        related_order=order, affects_customer_balance=True,
    ).order_by('pk'))
    before_refunds = PaymentTransaction.objects.filter(
        related_order=order, transaction_type=PaymentTransaction.TYPE_REFUND,
    ).values_list('pk', flat=True)
    existing_refund_ids = list(before_refunds)
    order = cancel_order(order=order, user=user)
    new_refunds = PaymentTransaction.objects.filter(
        related_order=order, transaction_type=PaymentTransaction.TYPE_REFUND,
    ).exclude(pk__in=existing_refund_ids)
    account_refunds = {
        row['cash_account_id']: row['amount']
        for row in new_refunds.values('cash_account_id').annotate(amount=Sum('amount'))
    }
    for collection in collections:
        reversed_amount = min(collection.amount, account_refunds.get(collection.cash_account_id, 0))
        if reversed_amount <= 0:
            continue
        old_amount = collection.amount
        collection.amount -= reversed_amount
        collection.save(update_fields=['amount', 'updated_at'])
        account_refunds[collection.cash_account_id] -= reversed_amount
        log_audit(
            user=user, action=AuditLog.ACTION_UPDATE, section=AuditLog.SECTION_FINANCE,
            model_name='SalesRepCollection', object_id=collection.pk, object_repr=str(collection),
            changes_before={'amount': str(old_amount)}, changes_after={'amount': str(collection.amount)},
            notes=f'عكس التحصيل لحذف الفاتورة {invoice.invoice_number}',
        )
    for movement in ledger_movements:
        if not order.customer_id:
            continue
        original_is_credit = (
            movement.transaction_type == PaymentTransaction.TYPE_CUSTOMER_ALLOWED_DISCOUNT
            or movement.direction == PaymentTransaction.DIRECTION_IN
        )
        record_customer_balance_adjustment(
            customer=order.customer, amount=movement.amount, user=user,
            direction=PaymentTransaction.DIRECTION_OUT if original_is_credit else PaymentTransaction.DIRECTION_IN,
            cash_account=movement.cash_account,
            notes=f'عكس تسوية رصيد لحذف الفاتورة {invoice.invoice_number}',
        )
    log_audit(
        user=user, action=AuditLog.ACTION_DELETE, section=AuditLog.SECTION_ORDERS,
        model_name='Invoice', object_id=invoice.pk, object_repr=str(invoice),
        changes_before={'status': old_status, 'remaining_amount': old_remaining, 'snapshot': invoice.snapshot},
        changes_after={'status': order.status, 'remaining_amount': str(order.remaining_amount)},
        notes=f'حذف الفاتورة {invoice.invoice_number} وعكس المخزون والتحصيل مع حفظ السجل للمراجعة',
    )
    return invoice


def generate_invoice_number(*, branch_id, invoice_date=None):
    """Return the next unused invoice number for a branch and date.

    Counting rows is unsafe because deleting an older invoice (or backdating an
    invoice) can make ``count + 1`` point at a number that already exists.  The
    caller locks the branch row, so finding the highest suffix is also safe when
    two invoices are issued concurrently in the same branch.
    """
    invoice_date = invoice_date or timezone.localdate()
    prefix = f'INV-{invoice_date:%Y%m%d}-'
    numbers = Invoice.all_objects.filter(
        branch_id=branch_id,
        invoice_number__startswith=prefix,
    ).values_list('invoice_number', flat=True)
    highest_sequence = 0
    for number in numbers:
        suffix = number.removeprefix(prefix)
        if suffix.isdigit():
            highest_sequence = max(highest_sequence, int(suffix))
    return f'{prefix}{highest_sequence + 1:04d}'


def build_invoice_snapshot(order):
    company = CompanySettings.load()
    customer = order.customer
    items = []
    for item in order.items.select_related(
        'variant__product', 'variant__color', 'variant__size',
        'warehouse__assigned_user',
    ):
        variant = item.variant
        items.append({
            'product_name': variant.product.name if variant else 'صنف محذوف',
            'sku': variant.product.sku if variant else '',
            'variant_sku': variant.variant_sku if variant else '',
            'color': str(variant.color or '-') if variant else '-',
            'size': str(variant.size or '-') if variant else '-',
            'warehouse': str(item.warehouse_or_sales_rep or '-'),
            'quantity': item.quantity,
            'unit_price': str(item.unit_price),
            'discount': str(item.discount),
            'total': str(item.total),
        })
    return {
        'customer_name': str(customer) if customer else 'عميل نقدي',
        'customer_phone': customer.phone if customer else '',
        'company': {
            'name': company.company_name or '',
            'phone': company.phone or '',
            'email': company.email or '',
            'address': company.address or '',
            'tax_number': company.tax_number or '',
            'invoice_notes': company.invoice_notes or '',
        },
        'items': items,
    }


@transaction.atomic
def generate_invoice(order, user=None):
    allowed_statuses = {
        Order.STATUS_CONFIRMED,
        Order.STATUS_PREPARING,
        Order.STATUS_READY,
        Order.STATUS_COMPLETED,
        Order.STATUS_PARTIALLY_RETURNED,
    }
    if order.status not in allowed_statuses:
        raise ValidationError('لا يمكن إصدار فاتورة نهائية لهذا المستند في حالته الحالية')
    if order.document_type == Order.DOCUMENT_QUOTE:
        raise ValidationError('لا يمكن إصدار فاتورة نهائية من تسعيرة غير مؤكدة')
    # Serialise number allocation per branch. Locking Invoice rows alone cannot
    # protect an empty date range, while the parent branch row always exists.
    Branch.objects.select_for_update().get(pk=order.branch_id)
    invoice_date = timezone.localtime(order.created_at).date() if order.created_at else timezone.localdate()
    invoice, created = Invoice.objects.get_or_create(
        order=order,
        defaults={
            'invoice_number': generate_invoice_number(
                branch_id=order.branch_id,
                invoice_date=invoice_date,
            ),
            'snapshot': build_invoice_snapshot(order),
        },
    )
    if not invoice.snapshot:
        invoice.snapshot = build_invoice_snapshot(order)
        invoice.save(update_fields=['snapshot'])
    if created and order.created_at:
        Invoice.objects.filter(pk=invoice.pk).update(issued_at=order.created_at)
        invoice.issued_at = order.created_at
    if order.document_type == Order.DOCUMENT_SALE and order.total > 0 and order.payment_method != Order.METHOD_CREDIT:
        record_order_sale_payment(order=order, user=user or order.created_by, notes=f'قيمة فاتورة تلقائية {invoice.invoice_number}')
    return invoice
