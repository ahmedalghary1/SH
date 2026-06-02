from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from orders.models import Order

from .models import Invoice


def generate_invoice_number():
    today = timezone.localdate().strftime('%Y%m%d')
    count = Invoice.objects.filter(issued_at__date=timezone.localdate()).count() + 1
    return f'INV-{today}-{count:04d}'


@transaction.atomic
def generate_invoice(order):
    if order.status == Order.STATUS_DRAFT:
        raise ValidationError('لا يمكن إصدار فاتورة لطلب مسودة')
    invoice, _ = Invoice.objects.get_or_create(order=order, defaults={'invoice_number': generate_invoice_number()})
    return invoice
