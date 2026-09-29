from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.models import Branch
from finance.services import record_order_sale_payment
from orders.models import Order
from settings_app.models import CompanySettings

from .models import Invoice


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
