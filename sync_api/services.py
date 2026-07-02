import hashlib
import json
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from accounts.models import User
from customers.models import Customer
from finance.models import CashAccount, PaymentTransaction
from finance.services import (
    add_expense,
    collect_customer_balance_payment,
    collect_order_payment,
    record_customer_refund_payment,
    record_transaction,
    transfer_between_accounts,
)
from inventory.models import Stock, StockMovement, Warehouse
from inventory.services import adjust_stock, stock_in, stock_out, transfer_stock
from orders.models import Order, OrderItem
from orders.services import create_order
from products.models import Product, ProductVariant
from returns.models import SalesReturn
from returns.services import add_exchange_item, add_return_item, create_sales_return
from sales_reps import services as sales_rep_services
from sales_reps.models import SalesRepStockAssignment

from .models import SyncOperation


def payload_hash(payload):
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def response_success(local_uuid, server_id, model, **extra):
    payload = {'local_uuid': local_uuid, 'status': 'success', 'server_id': server_id, 'server_model': model}
    payload.update(extra)
    return payload


def response_failed(local_uuid, error, status='failed'):
    return {'local_uuid': local_uuid, 'status': status, 'error': str(error)}


def _form_payload(operation):
    payload = operation.get('payload') or {}
    form = payload.get('form') or payload.get('fields') or {}
    return form if isinstance(form, dict) else {}


def _payload_timestamp(operation, data=None):
    payload = operation.get('payload') or {}
    candidates = [
        (data or {}).get('updated_at') if isinstance(data, dict) else None,
        payload.get('updated_at'),
        payload.get('queued_at'),
        operation.get('timestamp'),
    ]
    for value in candidates:
        if not value:
            continue
        parsed = parse_datetime(str(value))
        if parsed:
            return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)
    return timezone.now()


def _server_timestamp(obj):
    value = getattr(obj, 'updated_at', None) or getattr(obj, 'created_at', None)
    if value and timezone.is_naive(value):
        return timezone.make_aware(value)
    return value


def _server_is_newer(obj, local_timestamp):
    server_timestamp = _server_timestamp(obj)
    return bool(server_timestamp and local_timestamp and server_timestamp > local_timestamp)


def _is_int(value):
    return str(value or '').isdigit()


def _model_by_pk(model, value):
    if not _is_int(value):
        return None
    return model.objects.filter(pk=value).first()


def _date_value(value):
    return parse_date(str(value)) if value else None


def _find_synced_object_id(*, device_id, entity_type, local_uuid):
    operation = SyncOperation.objects.filter(
        device_id=device_id,
        entity_type=entity_type,
        local_uuid=local_uuid,
        status=SyncOperation.STATUS_SUCCESS,
    ).exclude(server_object_id__isnull=True).order_by('-created_at').first()
    return operation.server_object_id if operation else None


def _customer_from_payload(payload, device_id):
    server_id = payload.get('customer_server_id') or payload.get('server_id')
    raw_customer = payload.get('customer')
    if not server_id and _is_int(raw_customer):
        server_id = raw_customer
    local_uuid = payload.get('customer_local_uuid') or payload.get('local_uuid')
    if not local_uuid and raw_customer and not _is_int(raw_customer):
        local_uuid = raw_customer
    if not server_id and local_uuid:
        server_id = _find_synced_object_id(device_id=device_id, entity_type='customer', local_uuid=local_uuid)
    if server_id:
        return Customer.objects.filter(pk=server_id).first()
    phone = (payload.get('phone') or '').strip()
    if phone:
        return Customer.objects.filter(phone=phone).order_by('-created_at').first()
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
    elif amount < 0:
        tx = record_customer_refund_payment(
            customer=customer,
            amount=abs(amount),
            user=user,
            cash_account=cash_account,
            notes=payment.get('notes') or '',
        )
    else:
        transactions = collect_customer_balance_payment(
            customer=customer,
            amount=amount,
            user=user,
            cash_account=cash_account,
            notes=payment.get('notes') or '',
        )
        tx = transactions[-1]
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


def _json_items(value):
    if isinstance(value, list):
        return value
    try:
        loaded = json.loads(value or '[]')
    except (TypeError, json.JSONDecodeError):
        return []
    return loaded if isinstance(loaded, list) else []


def _normalize_order_payload(operation):
    payload = operation.get('payload') or {}
    if payload.get('order') or payload.get('items'):
        return payload.get('order') or {}, payload.get('items') or []
    form = _form_payload(operation)
    order_data = {
        'local_uuid': payload.get('local_uuid') or operation.get('local_uuid'),
        'customer': form.get('customer') or '',
        'customer_server_id': form.get('customer') if _is_int(form.get('customer')) else '',
        'customer_local_uuid': '' if _is_int(form.get('customer')) else form.get('customer') or '',
        'document_type': form.get('document_type') or Order.DOCUMENT_SALE,
        'order_type': form.get('order_type') or Order.TYPE_B2C,
        'payment_method': form.get('payment_method') or Order.METHOD_CASH,
        'warehouse': form.get('warehouse') or '',
        'discount': form.get('discount_amount') or '0',
        'discount_amount': form.get('discount_amount') or '0',
        'discount_percentage': form.get('discount_percentage') or '0',
        'paid_amount': form.get('paid_amount') or '0',
        'notes': form.get('notes') or '',
        'action': form.get('action') or 'confirm',
        'updated_at': payload.get('updated_at'),
    }
    items = _json_items(form.get('items_json'))
    for item in items:
        item.setdefault('variant_server_id', item.get('variant_id'))
        item.setdefault('warehouse_server_id', item.get('warehouse_id'))
    return order_data, items


def _order_from_payload(order_data, operation):
    server_id = order_data.get('server_id')
    if not server_id and _is_int(order_data.get('id')):
        server_id = order_data.get('id')
    if not server_id and order_data.get('local_uuid'):
        server_id = _find_synced_object_id(
            device_id=operation.get('device_id') or '',
            entity_type='order',
            local_uuid=order_data.get('local_uuid'),
        )
    return _model_by_pk(Order, server_id)


@transaction.atomic
def process_customer(operation, user):
    customer_data = operation['payload'].get('customer') or _form_payload(operation)
    local_uuid = customer_data.get('local_uuid') or operation.get('local_uuid')
    local_timestamp = _payload_timestamp(operation, customer_data)
    phone = (customer_data.get('phone') or '').strip()
    server_id = customer_data.get('server_id')
    if not server_id and _is_int(customer_data.get('id')):
        server_id = customer_data.get('id')
    if not server_id and local_uuid:
        server_id = _find_synced_object_id(
            device_id=operation.get('device_id') or '',
            entity_type='customer',
            local_uuid=local_uuid,
        )
    customer = _model_by_pk(Customer, server_id)
    if customer is None and phone:
        customer = Customer.objects.filter(phone=phone).order_by('-created_at').first()

    if operation.get('operation_type') == 'delete':
        if customer is None:
            return response_success(operation['local_uuid'], None, 'Customer', resolution='server_deleted')
        if _server_is_newer(customer, local_timestamp):
            return response_success(operation['local_uuid'], customer.pk, 'Customer', resolution='server_newer_ignored')
        customer.is_active = False
        customer.save(update_fields=['is_active', 'updated_at'])
        return response_success(operation['local_uuid'], customer.pk, 'Customer', resolution='local_deleted')

    if customer is not None and operation.get('operation_type') != 'create' and _server_is_newer(customer, local_timestamp):
        return response_success(operation['local_uuid'], customer.pk, 'Customer', resolution='server_newer_ignored')

    fields = {
        'name': customer_data.get('name') or 'Offline customer',
        'phone': phone or f"offline-{local_uuid or operation['local_uuid']}",
        'whatsapp': customer_data.get('whatsapp') or '',
        'customer_type': customer_data.get('customer_type') or Customer.TYPE_RETAIL,
        'address': customer_data.get('address') or '',
        'credit_limit': Decimal(str(customer_data.get('credit_limit') or 0)),
        'opening_balance': Decimal(str(customer_data.get('opening_balance') or 0)),
    }
    if customer is None:
        customer = Customer.objects.create(created_by=user, **fields)
    else:
        for field, value in fields.items():
            setattr(customer, field, value)
        customer.is_active = customer_data.get('is_active', True) not in {False, 'false', '0', 0}
        customer.save(update_fields=[*fields.keys(), 'is_active', 'updated_at'])
    return response_success(operation['local_uuid'], customer.pk, 'Customer', resolution='local_applied')


@transaction.atomic
def process_order(operation, user):
    order_data, items_data = _normalize_order_payload(operation)
    local_timestamp = _payload_timestamp(operation, order_data)
    existing_order = _order_from_payload(order_data, operation)

    if operation.get('operation_type') == 'delete':
        if existing_order is None:
            return response_success(operation['local_uuid'], None, 'Order', resolution='server_deleted')
        if _server_is_newer(existing_order, local_timestamp):
            return response_success(operation['local_uuid'], existing_order.pk, 'Order', resolution='server_newer_ignored')
        existing_order.status = Order.STATUS_CANCELLED
        existing_order.save(update_fields=['status', 'updated_at'])
        return response_success(operation['local_uuid'], existing_order.pk, 'Order', resolution='local_deleted')

    if existing_order is not None and operation.get('operation_type') != 'create':
        if _server_is_newer(existing_order, local_timestamp):
            return response_success(operation['local_uuid'], existing_order.pk, 'Order', resolution='server_newer_ignored')
        existing_order.notes = order_data.get('notes') or existing_order.notes
        if order_data.get('status') in dict(Order.STATUS_CHOICES):
            existing_order.status = order_data['status']
        existing_order.save(update_fields=['notes', 'status', 'updated_at'])
        return response_success(operation['local_uuid'], existing_order.pk, 'Order', resolution='local_applied')

    customer = _customer_from_payload(order_data, operation.get('device_id') or '')
    if customer is None:
        raise ValidationError('Cannot create offline invoice before its customer is synced')

    default_warehouse = _model_by_pk(Warehouse, order_data.get('warehouse')) or _default_warehouse(user)
    if default_warehouse is None:
        raise ValidationError('No available warehouse for synced invoice')

    items = []
    for item in items_data:
        variant = ProductVariant.objects.get(pk=item.get('variant_server_id') or item.get('variant_id'))
        item_warehouse = _model_by_pk(Warehouse, item.get('warehouse_server_id') or item.get('warehouse_id')) or default_warehouse
        items.append({
            'variant': variant,
            'warehouse': item_warehouse,
            'quantity': int(item.get('quantity') or 0),
            'unit_price': Decimal(str(item.get('unit_price') or 0)),
            'discount_amount': Decimal(str(item.get('discount_amount') or item.get('discount') or 0)),
            'discount_percentage': Decimal(str(item.get('discount_percentage') or 0)),
        })
    confirm = order_data.get('action') in {'confirm', 'new_invoice'}
    if order_data.get('document_type') == Order.DOCUMENT_QUOTE:
        confirm = False
    order = create_order(
        order_data={
            'customer': customer,
            'warehouse': default_warehouse,
            'document_type': order_data.get('document_type') or Order.DOCUMENT_SALE,
            'order_type': order_data.get('order_type') or Order.TYPE_B2C,
            'payment_method': order_data.get('payment_method') or Order.METHOD_CASH,
            'paid_amount': Decimal(str(order_data.get('paid_amount') or 0)),
            'notes': order_data.get('notes') or '',
            'discount_amount': Decimal(str(order_data.get('discount_amount') or order_data.get('discount') or 0)),
            'discount_percentage': Decimal(str(order_data.get('discount_percentage') or 0)),
        },
        items=items,
        user=user,
        confirm=confirm,
    )
    return response_success(operation['local_uuid'], order.pk, 'Order', resolution='local_applied')


@transaction.atomic
def process_payment(operation, user):
    payload = operation.get('payload') or {}
    payment = payload.get('payment') or _form_payload(operation)
    path = payload.get('original_url') or ''
    amount = Decimal(str(payment.get('amount') or 0))
    cash_account = _model_by_pk(CashAccount, payment.get('cash_account')) or CashAccount.get_default()
    transaction_date = _date_value(payment.get('transaction_date'))

    if 'expense' in path:
        tx = add_expense(
            amount=amount,
            cash_account=cash_account,
            user=user,
            notes=payment.get('notes') or '',
            transaction_date=transaction_date,
        )
        return response_success(operation['local_uuid'], tx.pk, 'PaymentTransaction', resolution='local_applied')

    if 'transfer' in path:
        from_account = _model_by_pk(CashAccount, payment.get('from_account'))
        to_account = _model_by_pk(CashAccount, payment.get('to_account'))
        out_tx, _ = transfer_between_accounts(
            from_account=from_account,
            to_account=to_account,
            amount=amount,
            user=user,
            notes=payment.get('notes') or '',
            transaction_date=transaction_date,
        )
        return response_success(operation['local_uuid'], out_tx.pk, 'PaymentTransaction', resolution='local_applied')

    order_id = payment.get('order_server_id') or payment.get('order')
    if not _is_int(order_id) and payment.get('order_local_uuid'):
        order_id = _find_synced_object_id(device_id=operation.get('device_id') or '', entity_type='order', local_uuid=payment['order_local_uuid'])
    customer = _customer_from_payload(payment, operation.get('device_id') or '')
    if order_id:
        order = Order.objects.get(pk=order_id)
        tx = collect_order_payment(
            order=order,
            amount=amount,
            user=user,
            cash_account=cash_account,
            notes=payment.get('notes') or '',
            transaction_date=transaction_date,
        )
    elif amount < 0:
        tx = record_customer_refund_payment(
            customer=customer,
            amount=abs(amount),
            user=user,
            cash_account=cash_account,
            notes=payment.get('notes') or '',
            transaction_date=transaction_date,
        )
    else:
        if customer is None:
            raise ValidationError('Cannot sync customer payment without a customer')
        transactions = collect_customer_balance_payment(
            customer=customer,
            amount=amount,
            user=user,
            cash_account=cash_account,
            notes=payment.get('notes') or '',
            transaction_date=transaction_date,
        )
        tx = transactions[-1]
    return response_success(operation['local_uuid'], tx.pk, 'PaymentTransaction', resolution='local_applied')


def _order_for_return(data, operation):
    order_id = data.get('order_server_id') or data.get('order')
    if not _is_int(order_id) and data.get('order_local_uuid'):
        order_id = _find_synced_object_id(device_id=operation.get('device_id') or '', entity_type='order', local_uuid=data['order_local_uuid'])
    order = _model_by_pk(Order, order_id)
    invoice_number = (data.get('invoice_number') or '').strip()
    if order is None and invoice_number:
        order = Order.objects.filter(order_number__iexact=invoice_number).first()
    if order is None and invoice_number:
        order = Order.objects.filter(invoice__invoice_number__iexact=invoice_number).first()
    return order


@transaction.atomic
def process_return(operation, user):
    payload = operation.get('payload') or {}
    data = payload.get('return') or _form_payload(operation)
    order = _order_for_return(data, operation)
    if order is None:
        raise ValidationError('Cannot sync return without a synced invoice')

    sales_return = create_sales_return(
        order=order,
        return_type=data.get('return_type') or SalesReturn.TYPE_PARTIAL_RETURN,
        reason=data.get('reason') or '',
        user=user,
    )

    selected_items = payload.get('items') or []
    if not selected_items:
        for key, value in data.items():
            if not str(key).startswith('selected_') or value != 'on':
                continue
            item_id = str(key).replace('selected_', '', 1)
            selected_items.append({
                'original_order_item': item_id,
                'quantity': data.get(f'quantity_{item_id}') or 0,
                'condition': data.get(f'condition_{item_id}') or 'good',
                'return_to_stock': data.get(f'return_to_stock_{item_id}', 'on') == 'on',
                'notes': data.get(f'notes_{item_id}') or '',
            })
    for item_data in selected_items:
        order_item = OrderItem.objects.get(pk=item_data.get('original_order_item'), order=order)
        add_return_item(
            sales_return=sales_return,
            original_order_item=order_item,
            quantity=item_data.get('quantity'),
            condition=item_data.get('condition') or 'good',
            return_to_stock=item_data.get('return_to_stock', True),
            notes=item_data.get('notes') or '',
        )

    exchange_items = payload.get('exchange_items') or []
    if not exchange_items:
        for key, variant_id in data.items():
            if not str(key).startswith('new_product_variant_') or not variant_id:
                continue
            index = str(key).replace('new_product_variant_', '', 1)
            exchange_items.append({
                'new_product_variant': variant_id,
                'quantity': data.get(f'new_quantity_{index}') or 0,
                'new_unit_price': data.get(f'new_price_{index}') or 0,
            })
    if exchange_items:
        old_item = sales_return.items.first()
        if not old_item:
            raise ValidationError('Exchange requires a returned item')
        for item_data in exchange_items:
            add_exchange_item(
                sales_return=sales_return,
                old_order_item=old_item.original_order_item,
                new_product_variant=ProductVariant.objects.get(pk=item_data.get('new_product_variant')),
                quantity=item_data.get('quantity'),
                new_unit_price=item_data.get('new_unit_price'),
                notes=item_data.get('notes') or '',
            )
    return response_success(operation['local_uuid'], sales_return.pk, 'SalesReturn', resolution='local_applied')


@transaction.atomic
def process_stock(operation, user):
    payload = operation.get('payload') or {}
    data = payload.get('stock') or _form_payload(operation)
    path = payload.get('original_url') or ''
    variant = _model_by_pk(ProductVariant, data.get('variant') or data.get('product_variant'))
    if variant is None:
        raise ValidationError('Missing product variant for stock sync')
    quantity = int(data.get('quantity') or 0)
    note = data.get('note') or data.get('notes') or ''

    if 'stock-in' in path:
        movement = stock_in(
            variant=variant,
            warehouse=Warehouse.objects.get(pk=data.get('warehouse')),
            quantity=quantity,
            user=user,
            note=note,
        )
    elif 'stock-out' in path:
        movement = stock_out(
            variant=variant,
            warehouse=Warehouse.objects.get(pk=data.get('warehouse')),
            quantity=quantity,
            user=user,
            note=note,
        )
    elif 'transfer' in path:
        movement = transfer_stock(
            variant=variant,
            from_warehouse=Warehouse.objects.get(pk=data.get('from_warehouse')),
            to_warehouse=Warehouse.objects.get(pk=data.get('to_warehouse')),
            quantity=quantity,
            user=user,
            note=note,
        )
    elif 'representative-issue' in path:
        representative = User.objects.get(pk=data.get('representative'))
        rep_warehouse, _ = Warehouse.objects.get_or_create(
            warehouse_type=Warehouse.TYPE_REPRESENTATIVE,
            assigned_user=representative,
            defaults={'name': f'Assignment {representative}', 'is_active': True},
        )
        movement = transfer_stock(
            variant=variant,
            from_warehouse=Warehouse.objects.get(pk=data.get('from_warehouse')),
            to_warehouse=rep_warehouse,
            quantity=quantity,
            user=user,
            note=note,
        )
    elif 'representative-return' in path:
        representative = User.objects.get(pk=data.get('representative'))
        rep_warehouse = Warehouse.objects.get(warehouse_type=Warehouse.TYPE_REPRESENTATIVE, assigned_user=representative, is_active=True)
        movement = transfer_stock(
            variant=variant,
            from_warehouse=rep_warehouse,
            to_warehouse=Warehouse.objects.get(pk=data.get('to_warehouse')),
            quantity=quantity,
            user=user,
            note=note,
        )
    else:
        movement = adjust_stock(
            variant=variant,
            warehouse=Warehouse.objects.get(pk=data.get('warehouse')),
            new_quantity=int(data.get('new_quantity') or 0),
            user=user,
            note=note,
        )
    return response_success(operation['local_uuid'], movement.pk, 'StockMovement', resolution='local_applied')


@transaction.atomic
def process_product(operation, user):
    product_data = operation['payload'].get('product') or _form_payload(operation)
    local_timestamp = _payload_timestamp(operation, product_data)
    product = _model_by_pk(Product, product_data.get('server_id') or product_data.get('id'))
    sku = product_data.get('sku') or product_data.get('product_sku')
    if product is None and sku:
        product = Product.objects.filter(sku=sku).first()
    if operation.get('operation_type') == 'delete':
        if product is None:
            return response_success(operation['local_uuid'], None, 'Product', resolution='server_deleted')
        product.is_active = False
        product.save(update_fields=['is_active', 'updated_at'])
        return response_success(operation['local_uuid'], product.pk, 'Product', resolution='local_deleted')
    if product is not None and operation.get('operation_type') != 'create' and _server_is_newer(product, local_timestamp):
        return response_success(operation['local_uuid'], product.pk, 'Product', resolution='server_newer_ignored')
    if product is None:
        product = Product.objects.create(
            name=product_data.get('name') or product_data.get('new_product_name') or 'Offline product',
            sku=sku or f"offline-{operation['local_uuid']}",
            retail_price=Decimal(str(product_data.get('retail_price') or 0)),
            wholesale_price=Decimal(str(product_data.get('wholesale_price') or 0)),
        )
    else:
        product.name = product_data.get('name') or product.name
        product.retail_price = Decimal(str(product_data.get('retail_price') or product.retail_price or 0))
        product.wholesale_price = Decimal(str(product_data.get('wholesale_price') or product.wholesale_price or 0))
        product.save(update_fields=['name', 'retail_price', 'wholesale_price', 'updated_at'])
    return response_success(operation['local_uuid'], product.pk, 'Product', resolution='local_applied')


@transaction.atomic
def process_driver_action(operation, user):
    payload = operation.get('payload') or {}
    data = payload.get('driver_action') or _form_payload(operation)
    path = payload.get('original_url') or ''
    notes = data.get('notes') or data.get('note') or ''

    if 'assign' in path:
        assignment = sales_rep_services.assign_stock_to_sales_rep(
            sales_rep=User.objects.get(pk=data.get('sales_rep')),
            product_variant=ProductVariant.objects.get(pk=data.get('product_variant')),
            source_warehouse=Warehouse.objects.get(pk=data.get('source_warehouse')),
            quantity=int(data.get('quantity') or 0),
            assigned_by=user,
            notes=notes,
        )
        return response_success(operation['local_uuid'], assignment.pk, 'SalesRepStockAssignment', resolution='local_applied')
    if 'return-stock' in path:
        assignment = sales_rep_services.return_stock_from_sales_rep(
            assignment=SalesRepStockAssignment.objects.get(pk=data.get('assignment')),
            quantity=int(data.get('quantity') or 0),
            user=user,
            notes=notes,
        )
        return response_success(operation['local_uuid'], assignment.pk, 'SalesRepStockAssignment', resolution='local_applied')
    if 'sale' in path:
        assignment = sales_rep_services.record_sales_rep_sale(
            assignment=SalesRepStockAssignment.objects.get(pk=data.get('assignment')),
            quantity=int(data.get('quantity') or 0),
            user=user,
            notes=notes,
        )
        return response_success(operation['local_uuid'], assignment.pk, 'SalesRepStockAssignment', resolution='local_applied')
    if 'handover' in path:
        amount = sales_rep_services.handover_sales_rep_cash(
            sales_rep=User.objects.get(pk=data.get('sales_rep')),
            amount=Decimal(str(data.get('amount') or 0)),
            target_cash_account=CashAccount.objects.get(pk=data.get('target_cash_account')),
            user=user,
            source_cash_account=_model_by_pk(CashAccount, data.get('source_cash_account')),
            notes=notes,
        )
        return response_success(operation['local_uuid'], None, 'SalesRepHandover', amount=str(amount), resolution='local_applied')
    collection = sales_rep_services.record_sales_rep_collection(
        sales_rep=User.objects.get(pk=data.get('sales_rep')),
        amount=Decimal(str(data.get('amount') or 0)),
        user=user,
        cash_account=_model_by_pk(CashAccount, data.get('cash_account')),
        customer=_model_by_pk(Customer, data.get('customer')),
        order=_model_by_pk(Order, data.get('order')),
        notes=notes,
    )
    return response_success(operation['local_uuid'], collection.pk, 'SalesRepCollection', resolution='local_applied')


PROCESSORS = {
    'customer': process_customer,
    'order': process_order,
    'payment': process_payment,
    'return': process_return,
    'stock': process_stock,
    'product': process_product,
    'driver_action': process_driver_action,
}


def process_operation(operation, user):
    current_payload_hash = payload_hash(operation.get('payload') or {})
    existing = SyncOperation.objects.filter(idempotency_key=operation['idempotency_key']).first()
    if existing:
        if existing.payload_hash and existing.payload_hash != current_payload_hash:
            return response_failed(
                operation.get('local_uuid'),
                'Idempotency key already used with different payload',
                'failed_conflict',
            )
        if existing.status in {SyncOperation.STATUS_SUCCESS, SyncOperation.STATUS_CONFLICT}:
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

    operation_record = existing or SyncOperation(idempotency_key=operation['idempotency_key'])
    operation_record.device_id = operation.get('device_id') or ''
    operation_record.user = user
    operation_record.entity_type = operation.get('entity_type') or ''
    operation_record.operation_type = operation.get('operation_type') or ''
    operation_record.local_uuid = operation.get('local_uuid') or ''
    operation_record.server_model = server_model
    operation_record.server_object_id = server_object_id
    operation_record.payload_hash = current_payload_hash
    operation_record.status = status
    operation_record.response_json = result
    operation_record.save()
    return result
