import hashlib
import json
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from customers.models import Customer
from finance.models import CashAccount, PaymentTransaction
from finance.services import collect_order_payment, record_customer_payment, record_transaction
from inventory.models import Warehouse
from orders.models import Order
from orders.services import create_order
from products.models import ProductVariant
from returns.models import SalesReturn
from returns.services import create_sales_return

from .models import SyncOperation


def payload_hash(payload):
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def response_success(local_uuid, server_id, model):
    return {'local_uuid': local_uuid, 'status': 'success', 'server_id': server_id, 'server_model': model}


def response_failed(local_uuid, error, status='failed'):
    return {'local_uuid': local_uuid, 'status': status, 'error': str(error)}


def _find_synced_object_id(*, device_id, entity_type, local_uuid):
    operation = SyncOperation.objects.filter(
        device_id=device_id,
        entity_type=entity_type,
        local_uuid=local_uuid,
        status=SyncOperation.STATUS_SUCCESS,
    ).exclude(server_object_id__isnull=True).order_by('-created_at').first()
    return operation.server_object_id if operation else None


def _customer_from_payload(payload, device_id):
    server_id = payload.get('customer_server_id')
    local_uuid = payload.get('customer_local_uuid')
    if not server_id and local_uuid:
        server_id = _find_synced_object_id(device_id=device_id, entity_type='customer', local_uuid=local_uuid)
    if server_id:
        return Customer.objects.filter(pk=server_id).first()
    return None


def _default_warehouse(user):
    assigned = Warehouse.objects.filter(assigned_user=user, is_active=True).order_by('warehouse_type', 'pk').first()
    if assigned:
        return assigned
    return Warehouse.objects.filter(is_active=True).order_by('warehouse_type', 'pk').first()


@transaction.atomic
def process_customer(operation, user):
    customer_data = operation['payload'].get('customer', {})
    phone = (customer_data.get('phone') or '').strip()
    customer = None
    if phone:
        customer = Customer.objects.filter(phone=phone).first()
    if customer is None:
        customer = Customer.objects.create(
            name=customer_data.get('name') or 'عميل بدون اسم',
            phone=phone or f"offline-{customer_data.get('local_uuid')}",
            whatsapp=customer_data.get('whatsapp') or '',
            customer_type=customer_data.get('customer_type') or Customer.TYPE_RETAIL,
            address=customer_data.get('address') or '',
            credit_limit=Decimal(str(customer_data.get('credit_limit') or 0)),
            opening_balance=Decimal(str(customer_data.get('opening_balance') or 0)),
            created_by=user,
        )
    return response_success(operation['local_uuid'], customer.pk, 'Customer')


@transaction.atomic
def process_order(operation, user):
    payload = operation['payload']
    order_data = payload.get('order', {})
    items_data = payload.get('items', [])
    customer = _customer_from_payload(order_data, operation['device_id'])
    if customer is None:
        raise ValidationError('لا يمكن إنشاء فاتورة بدون عميل متزامن')
    warehouse = _default_warehouse(user)
    if warehouse is None:
        raise ValidationError('لا يوجد مخزن متاح للمستخدم')
    items = []
    for item in items_data:
        variant = ProductVariant.objects.get(pk=item['variant_server_id'])
        items.append({
            'variant': variant,
            'warehouse': warehouse,
            'quantity': int(item['quantity']),
            'unit_price': Decimal(str(item.get('unit_price') or 0)),
            'discount': Decimal(str(item.get('discount') or 0)),
        })
    order = create_order(
        order_data={
            'customer': customer,
            'warehouse': warehouse,
            'document_type': order_data.get('document_type') or Order.DOCUMENT_SALE,
            'order_type': order_data.get('order_type') or Order.TYPE_B2C,
            'payment_method': order_data.get('payment_method') or Order.METHOD_CASH,
            'paid_amount': Decimal(str(order_data.get('paid_amount') or 0)),
            'notes': order_data.get('notes') or '',
            'discount_amount': Decimal(str(order_data.get('discount') or 0)),
        },
        items=items,
        user=user,
        confirm=True,
    )
    return response_success(operation['local_uuid'], order.pk, 'Order')


@transaction.atomic
def process_payment(operation, user):
    payment = operation['payload'].get('payment', {})
    amount = Decimal(str(payment.get('amount') or 0))
    order_id = payment.get('order_server_id')
    if not order_id and payment.get('order_local_uuid'):
        order_id = _find_synced_object_id(device_id=operation['device_id'], entity_type='order', local_uuid=payment['order_local_uuid'])
    customer = _customer_from_payload(payment, operation['device_id'])
    cash_account = CashAccount.get_default()
    if order_id:
        order = Order.objects.get(pk=order_id)
        tx = collect_order_payment(order=order, amount=amount, user=user, cash_account=cash_account, notes=payment.get('notes') or '')
    else:
        tx = record_customer_payment(order=None, customer=customer, amount=amount, user=user, cash_account=cash_account, notes=payment.get('notes') or '')
    return response_success(operation['local_uuid'], tx.pk, 'PaymentTransaction')


@transaction.atomic
def process_return(operation, user):
    data = operation['payload'].get('return', {})
    order_id = data.get('order_server_id')
    if not order_id and data.get('order_local_uuid'):
        order_id = _find_synced_object_id(device_id=operation['device_id'], entity_type='order', local_uuid=data['order_local_uuid'])
    if not order_id:
        raise ValidationError('لا يمكن إنشاء مرتجع بدون فاتورة متزامنة')
    order = Order.objects.get(pk=order_id)
    sales_return = create_sales_return(
        order=order,
        return_type=data.get('return_type') or SalesReturn.TYPE_PARTIAL_RETURN,
        reason=data.get('reason') or '',
        user=user,
    )
    refund_amount = Decimal(str(data.get('refund_amount') or 0))
    if refund_amount > 0:
        sales_return.refund_amount = refund_amount
        sales_return.status = SalesReturn.STATUS_COMPLETED
        sales_return.approved_by = user
        sales_return.completed_by = user
        sales_return.save(update_fields=['refund_amount', 'status', 'approved_by', 'completed_by'])
        record_transaction(
            transaction_type=PaymentTransaction.TYPE_REFUND,
            direction=PaymentTransaction.DIRECTION_OUT,
            amount=refund_amount,
            cash_account=CashAccount.get_default(),
            related_order=order,
            related_customer=order.customer,
            notes=data.get('reason') or f'Offline return {operation["local_uuid"]}',
            created_by=user,
        )
    return response_success(operation['local_uuid'], sales_return.pk, 'SalesReturn')


PROCESSORS = {
    'customer': process_customer,
    'order': process_order,
    'payment': process_payment,
    'return': process_return,
}


def process_operation(operation, user):
    existing = SyncOperation.objects.filter(idempotency_key=operation['idempotency_key']).first()
    if existing:
        return existing.response_json

    processor = PROCESSORS.get(operation.get('entity_type'))
    if processor is None:
        result = response_failed(operation.get('local_uuid'), 'Unsupported entity type')
        status = SyncOperation.STATUS_FAILED
        server_model = None
        server_object_id = None
    else:
        try:
            result = processor(operation, user)
            status = SyncOperation.STATUS_SUCCESS
            server_model = result.get('server_model')
            server_object_id = str(result.get('server_id')) if result.get('server_id') else None
        except ValidationError as exc:
            result = response_failed(operation.get('local_uuid'), exc.messages[0] if hasattr(exc, 'messages') else exc, 'failed_conflict')
            status = SyncOperation.STATUS_CONFLICT
            server_model = None
            server_object_id = None
        except Exception as exc:
            result = response_failed(operation.get('local_uuid'), exc)
            status = SyncOperation.STATUS_FAILED
            server_model = None
            server_object_id = None

    SyncOperation.objects.create(
        idempotency_key=operation['idempotency_key'],
        device_id=operation.get('device_id') or '',
        user=user,
        entity_type=operation.get('entity_type') or '',
        operation_type=operation.get('operation_type') or '',
        local_uuid=operation.get('local_uuid') or '',
        server_model=server_model,
        server_object_id=server_object_id,
        payload_hash=payload_hash(operation.get('payload') or {}),
        status=status,
        response_json=result,
    )
    return result
