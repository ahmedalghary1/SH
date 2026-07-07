import base64
import binascii
import hashlib
import json
from decimal import Decimal

from django.core.files.base import ContentFile
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
    record_supplier_payment,
    record_transaction,
    transfer_between_accounts,
)
from inventory.models import Stock, StockMovement, Warehouse
from inventory.services import adjust_stock, stock_in, stock_out, transfer_stock
from invoices.models import Invoice
from orders.models import Order, OrderItem
from orders.services import cancel_order, confirm_order, create_order, return_order
from products.models import Category, Color, Product, ProductVariant, Size
from purchases.models import PurchaseOrder, Supplier
from purchases.services import (
    cancel_purchase_order,
    create_purchase_order,
    create_purchase_return,
    pay_supplier,
    receive_purchase_order_items,
)
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
            phone=phone,
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
        'phone': phone,
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
        requested_status = order_data.get('status')
        if requested_status == Order.STATUS_CONFIRMED and existing_order.status == Order.STATUS_DRAFT:
            confirm_order(order=existing_order, user=user)
            return response_success(operation['local_uuid'], existing_order.pk, 'Order', resolution='local_applied')
        if requested_status == Order.STATUS_CANCELLED:
            cancel_order(order=existing_order, user=user)
            return response_success(operation['local_uuid'], existing_order.pk, 'Order', resolution='local_applied')
        if requested_status == Order.STATUS_RETURNED:
            return_order(order=existing_order, user=user)
            return response_success(operation['local_uuid'], existing_order.pk, 'Order', resolution='local_applied')
        existing_order.notes = order_data.get('notes') or existing_order.notes
        if requested_status in dict(Order.STATUS_CHOICES):
            existing_order.status = requested_status
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


def _process_cash_account(operation, data):
    account = _model_by_pk(CashAccount, data.get('server_id') or data.get('id'))
    name = str(data.get('name') or '').strip() or 'Offline cash account'
    if account is None and name:
        account = CashAccount.objects.filter(name=name).order_by('-created_at').first()

    if operation.get('operation_type') == 'delete':
        if account is None:
            return response_success(operation['local_uuid'], None, 'CashAccount', resolution='server_deleted')
        account.is_active = False
        account.save(update_fields=['is_active', 'updated_at'])
        return response_success(operation['local_uuid'], account.pk, 'CashAccount', resolution='local_deleted')

    account_type = data.get('account_type') or CashAccount.TYPE_CASH
    valid_types = {choice[0] for choice in CashAccount.ACCOUNT_TYPE_CHOICES}
    if account_type not in valid_types:
        account_type = CashAccount.TYPE_CASH
    fields = {
        'name': name,
        'account_type': account_type,
        'assigned_user': _model_by_pk(User, data.get('assigned_user')),
        'balance': Decimal(str(data.get('balance') or 0)),
        'allow_overdraft': _bool_value(data.get('allow_overdraft'), False),
        'is_active': _bool_value(data.get('is_active'), True),
    }
    if account is None:
        account = CashAccount.objects.create(**fields)
    else:
        for field, value in fields.items():
            setattr(account, field, value)
        account.save(update_fields=[*fields.keys(), 'updated_at'])
    return response_success(operation['local_uuid'], account.pk, 'CashAccount', resolution='local_applied')


@transaction.atomic
def process_payment(operation, user):
    payload = operation.get('payload') or {}
    payment = payload.get('payment') or _form_payload(operation)
    path = payload.get('original_url') or ''
    if '/finance/accounts/' in path:
        return _process_cash_account(operation, payment)

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

    if 'supplier-payment' in path:
        supplier = _model_by_pk(Supplier, payment.get('supplier'))
        if supplier is None:
            raise ValidationError('Cannot sync supplier payment without a supplier')
        tx = record_supplier_payment(
            supplier=supplier,
            amount=amount,
            user=user,
            cash_account=cash_account,
            notes=payment.get('notes') or '',
            transaction_date=transaction_date,
        )
        return response_success(operation['local_uuid'], tx.pk, 'PaymentTransaction', resolution='local_applied')

    order_id = payment.get('order_server_id') or payment.get('order')
    if not order_id and '/invoices/' in path and '/payments/add/' in path:
        parts = [part for part in path.split('/') if part]
        invoice_id = parts[1] if len(parts) > 1 and parts[0] == 'invoices' else None
        invoice = _model_by_pk(Invoice, invoice_id)
        if invoice:
            order_id = invoice.order_id
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
    if '/inventory/warehouses/' in path:
        return _process_warehouse(operation, data)

    variant = _model_by_pk(ProductVariant, data.get('variant') or data.get('product_variant'))
    if variant is None:
        raise ValidationError('Missing product variant for stock sync')
    quantity = int(data.get('quantity') or 0)
    note = data.get('note') or data.get('notes') or ''

    if 'stock-in' in path or '/movements/in/' in path:
        movement = stock_in(
            variant=variant,
            warehouse=Warehouse.objects.get(pk=data.get('warehouse')),
            quantity=quantity,
            user=user,
            note=note,
        )
    elif 'stock-out' in path or '/movements/out/' in path:
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


def _first_value(value, default=''):
    if isinstance(value, list):
        for item in value:
            if item not in (None, ''):
                return item
        return default
    return default if value is None else value


def _list_values(value):
    if isinstance(value, list):
        return [item for item in value if item not in (None, '')]
    if value in (None, ''):
        return []
    return [value]


def _decimal_value(value, default='0'):
    return Decimal(str(_first_value(value, default) or default))


def _int_value(value, default=0):
    return int(_first_value(value, default) or default)


def _bool_value(value, default=True):
    raw = _first_value(value, default)
    if isinstance(raw, bool):
        return raw
    return str(raw).lower() in {'1', 'true', 'yes', 'on'}


def _related_by_id(model, value):
    return _model_by_pk(model, _first_value(value))


def _file_payload(data, field_name='image', index=0):
    files = data.get('_files') or {}
    payload = files.get(field_name)
    if isinstance(payload, list):
        payload = payload[index] if len(payload) > index else None
    if not isinstance(payload, dict) or not payload.get('data'):
        return None
    name = str(payload.get('name') or f'offline-{timezone.now().timestamp()}').replace('\\', '/').split('/')[-1]
    try:
        content = base64.b64decode(payload['data'])
    except (TypeError, ValueError, binascii.Error):
        return None
    return name, ContentFile(content)


def _save_payload_file(instance, field_name, file_payload):
    if not file_payload:
        return False
    name, content = file_payload
    getattr(instance, field_name).save(name, content, save=False)
    return True


def _category_from_product_data(data):
    category = _related_by_id(Category, data.get('category'))
    new_name = str(_first_value(data.get('new_category_name')) or '').strip()
    if category is None and new_name:
        category, _ = Category.objects.get_or_create(name=new_name, defaults={'is_active': True})
    return category


def _color_from_product_data(data):
    color = _related_by_id(Color, data.get('color'))
    new_name = str(_first_value(data.get('new_color_name')) or '').strip()
    if color is None and new_name:
        color, _ = Color.objects.get_or_create(name=new_name)
    return color


def _size_from_product_data(data):
    size = _related_by_id(Size, data.get('size'))
    new_name = str(_first_value(data.get('new_size_name')) or '').strip()
    if size is None and new_name:
        size, _ = Size.objects.get_or_create(name=new_name, defaults={'sort_order': 0})
    return size


def _warehouse_from_product_data(data):
    warehouse = _related_by_id(Warehouse, data.get('warehouse'))
    new_name = str(_first_value(data.get('new_warehouse_name')) or '').strip()
    if warehouse is None and new_name:
        warehouse, _ = Warehouse.objects.get_or_create(
            name=new_name,
            defaults={'warehouse_type': Warehouse.TYPE_MAIN, 'is_active': True},
        )
    return warehouse


def _offline_variant_sku(product, color=None, size=None):
    base = f'{product.sku}-{getattr(color, "pk", None) or "0"}-{getattr(size, "pk", None) or "0"}'
    sku = base
    counter = 2
    while ProductVariant.objects.filter(variant_sku=sku).exists():
        sku = f'{base}-{counter}'
        counter += 1
    return sku


def _has_initial_variant_data(data):
    return any(_first_value(data.get(field)) not in ('', None) for field in (
        'color',
        'new_color_name',
        'size',
        'new_size_name',
        'cost_price',
        'retail_price',
        'wholesale_price',
    ))


def _sync_initial_variant_and_stock(product, data, user):
    if not _has_initial_variant_data(data):
        return None
    color = _color_from_product_data(data)
    size = _size_from_product_data(data)
    variant = ProductVariant.objects.filter(product=product, color=color, size=size).first()
    fields = {
        'cost_price': _decimal_value(data.get('cost_price')),
        'retail_price': _decimal_value(data.get('retail_price')),
        'wholesale_price': _decimal_value(data.get('wholesale_price')),
    }
    fields['sale_price'] = fields['retail_price']
    if variant is None:
        variant = ProductVariant.objects.create(
            product=product,
            color=color,
            size=size,
            variant_sku=str(_first_value(data.get('variant_sku')) or '') or _offline_variant_sku(product, color, size),
            **fields,
        )
    else:
        for field, value in fields.items():
            setattr(variant, field, value)
        variant.save(update_fields=[*fields.keys(), 'updated_at'])

    variant_file = _file_payload(data, 'image', index=1)
    if variant_file and _save_payload_file(variant, 'image', variant_file):
        variant.save(update_fields=['image', 'updated_at'])

    quantity = _int_value(data.get('quantity'))
    warehouse = _warehouse_from_product_data(data)
    if quantity > 0 and warehouse:
        stock_in(
            variant=variant,
            warehouse=warehouse,
            quantity=quantity,
            user=user,
            note='Offline product opening balance',
            source='opening_balance',
            movement_type=StockMovement.TYPE_OPENING_BALANCE,
        )
        stock, _ = Stock.objects.get_or_create(warehouse=warehouse, variant=variant, defaults={'quantity': 0})
        stock.min_quantity = _int_value(data.get('min_quantity'))
        stock.save(update_fields=['min_quantity', 'updated_at'])
    return variant


def _sync_product_variants_from_update(product, data):
    for variant_id in _list_values(data.get('variant_id')):
        variant = ProductVariant.objects.filter(pk=variant_id, product=product).first()
        if variant is None:
            continue
        changed = []
        retail_price = data.get(f'variant_{variant_id}_retail_price')
        wholesale_price = data.get(f'variant_{variant_id}_wholesale_price')
        if retail_price not in (None, ''):
            variant.retail_price = _decimal_value(retail_price)
            variant.sale_price = variant.retail_price
            changed.extend(['retail_price', 'sale_price'])
        if wholesale_price not in (None, ''):
            variant.wholesale_price = _decimal_value(wholesale_price)
            changed.append('wholesale_price')
        if changed:
            variant.save(update_fields=[*set(changed), 'updated_at'])


def _sync_product_stock_from_update(product, data, user):
    for stock_id in _list_values(data.get('stock_id')):
        stock = Stock.objects.select_related('warehouse', 'variant').filter(pk=stock_id, variant__product=product).first()
        if stock is None:
            continue
        target_warehouse = _related_by_id(Warehouse, data.get(f'stock_{stock_id}_warehouse')) or stock.warehouse
        quantity = _int_value(data.get(f'stock_{stock_id}_quantity'), stock.quantity)
        min_quantity = _int_value(data.get(f'stock_{stock_id}_min_quantity'), stock.min_quantity)
        if target_warehouse != stock.warehouse and stock.quantity > 0:
            transfer_stock(
                variant=stock.variant,
                from_warehouse=stock.warehouse,
                to_warehouse=target_warehouse,
                quantity=stock.quantity,
                user=user,
                note=f'Offline product stock warehouse change {product.sku}',
            )
            stock = Stock.objects.filter(warehouse=target_warehouse, variant=stock.variant).first() or stock
        if stock.quantity != quantity:
            adjust_stock(
                variant=stock.variant,
                warehouse=target_warehouse,
                new_quantity=quantity,
                user=user,
                note=f'Offline product stock quantity change {product.sku}',
            )
            stock.refresh_from_db()
        stock.min_quantity = min_quantity
        stock.save(update_fields=['min_quantity', 'updated_at'])


def _process_category(operation, data):
    category = _related_by_id(Category, data.get('server_id') or data.get('id'))
    if operation.get('operation_type') == 'delete':
        if category is None:
            return response_success(operation['local_uuid'], None, 'Category', resolution='server_deleted')
        category.is_active = False
        category.save(update_fields=['is_active'])
        return response_success(operation['local_uuid'], category.pk, 'Category', resolution='local_deleted')
    fields = {
        'name': _first_value(data.get('name')) or 'Offline category',
        'is_active': _bool_value(data.get('is_active'), True),
    }
    if category is None:
        category = Category.objects.create(**fields)
    else:
        for field, value in fields.items():
            setattr(category, field, value)
        category.save(update_fields=list(fields.keys()))
    return response_success(operation['local_uuid'], category.pk, 'Category', resolution='local_applied')


def _process_color(operation, data):
    color = _related_by_id(Color, data.get('server_id') or data.get('id'))
    name = _first_value(data.get('name')) or 'Offline color'
    if color is None and name:
        color = Color.objects.filter(name=name).first()
    if operation.get('operation_type') == 'delete':
        return response_success(operation['local_uuid'], getattr(color, 'pk', None), 'Color', resolution='server_deleted')
    fields = {
        'name': name,
        'hex_code': _first_value(data.get('hex_code')) or None,
    }
    if color is None:
        color = Color.objects.create(**fields)
    else:
        for field, value in fields.items():
            setattr(color, field, value)
        color.save(update_fields=list(fields.keys()))
    return response_success(operation['local_uuid'], color.pk, 'Color', resolution='local_applied')


def _process_size(operation, data):
    size = _related_by_id(Size, data.get('server_id') or data.get('id'))
    name = _first_value(data.get('name')) or 'Offline size'
    if size is None and name:
        size = Size.objects.filter(name=name).first()
    if operation.get('operation_type') == 'delete':
        return response_success(operation['local_uuid'], getattr(size, 'pk', None), 'Size', resolution='server_deleted')
    fields = {
        'name': name,
        'sort_order': _int_value(data.get('sort_order')),
    }
    if size is None:
        size = Size.objects.create(**fields)
    else:
        for field, value in fields.items():
            setattr(size, field, value)
        size.save(update_fields=list(fields.keys()))
    return response_success(operation['local_uuid'], size.pk, 'Size', resolution='local_applied')


def _process_warehouse(operation, data):
    warehouse = _related_by_id(Warehouse, data.get('server_id') or data.get('id'))
    name = _first_value(data.get('name') or data.get('new_warehouse_name')) or 'Offline warehouse'
    if warehouse is None and name:
        warehouse = Warehouse.objects.filter(name=name).first()
    if operation.get('operation_type') == 'delete':
        if warehouse is None:
            return response_success(operation['local_uuid'], None, 'Warehouse', resolution='server_deleted')
        warehouse.is_active = False
        warehouse.save(update_fields=['is_active', 'updated_at'])
        return response_success(operation['local_uuid'], warehouse.pk, 'Warehouse', resolution='local_deleted')

    warehouse_type = _first_value(data.get('warehouse_type')) or Warehouse.TYPE_MAIN
    if warehouse_type not in {Warehouse.TYPE_MAIN, Warehouse.TYPE_STORE, Warehouse.TYPE_REPRESENTATIVE}:
        warehouse_type = Warehouse.TYPE_MAIN
    fields = {
        'name': name,
        'warehouse_type': warehouse_type,
        'is_active': _bool_value(data.get('is_active'), True),
    }
    if warehouse is None:
        warehouse = Warehouse.objects.create(**fields)
    else:
        for field, value in fields.items():
            setattr(warehouse, field, value)
        warehouse.save(update_fields=[*fields.keys(), 'updated_at'])
    return response_success(operation['local_uuid'], warehouse.pk, 'Warehouse', resolution='local_applied')


def _process_product_variant(operation, data):
    variant = _related_by_id(ProductVariant, data.get('server_id') or data.get('id'))
    if operation.get('operation_type') == 'delete':
        if variant is None:
            return response_success(operation['local_uuid'], None, 'ProductVariant', resolution='server_deleted')
        variant.is_active = False
        variant.save(update_fields=['is_active', 'updated_at'])
        return response_success(operation['local_uuid'], variant.pk, 'ProductVariant', resolution='local_deleted')

    product = _related_by_id(Product, data.get('product')) or getattr(variant, 'product', None)
    if product is None:
        raise ValidationError('Cannot sync product variant without a product')
    color = _color_from_product_data(data)
    size = _size_from_product_data(data)
    fields = {
        'product': product,
        'color': color,
        'size': size,
        'cost_price': _decimal_value(data.get('cost_price')),
        'retail_price': _decimal_value(data.get('retail_price')),
        'wholesale_price': _decimal_value(data.get('wholesale_price')),
        'is_active': _bool_value(data.get('is_active'), True),
    }
    fields['sale_price'] = fields['retail_price']
    if variant is None:
        variant = ProductVariant.objects.create(
            variant_sku=str(_first_value(data.get('variant_sku')) or '') or _offline_variant_sku(product, color, size),
            **fields,
        )
    else:
        for field, value in fields.items():
            setattr(variant, field, value)
        variant.save(update_fields=[*fields.keys(), 'sale_price', 'updated_at'])
    if _save_payload_file(variant, 'image', _file_payload(data, 'image', index=0)):
        variant.save(update_fields=['image', 'updated_at'])
    return response_success(operation['local_uuid'], variant.pk, 'ProductVariant', resolution='local_applied')


def _process_bulk_price_update(operation, data):
    updated = 0
    for variant_id in _list_values(data.get('variant_id')):
        variant = _related_by_id(ProductVariant, variant_id)
        if variant is None:
            continue
        price = data.get(f'price_{variant_id}')
        if price in (None, ''):
            continue
        variant.sale_price = _decimal_value(price)
        variant.retail_price = variant.sale_price
        variant.save(update_fields=['sale_price', 'retail_price', 'updated_at'])
        updated += 1
    return response_success(operation['local_uuid'], None, 'ProductVariant', updated=updated, resolution='local_applied')


@transaction.atomic
def process_product(operation, user):
    payload = operation.get('payload') or {}
    product_data = payload.get('product') or _form_payload(operation)
    path = payload.get('original_url') or ''
    if '/products/bulk-price-update/' in path:
        return _process_bulk_price_update(operation, product_data)
    if '/products/categories/' in path or '/products/ajax/quick-create-category/' in path:
        return _process_category(operation, product_data)
    if '/products/colors/' in path or '/products/ajax/quick-create-color/' in path:
        return _process_color(operation, product_data)
    if '/products/sizes/' in path or '/products/ajax/quick-create-size/' in path:
        return _process_size(operation, product_data)
    if '/products/ajax/quick-create-warehouse/' in path:
        return _process_warehouse(operation, product_data)
    if '/products/variants/' in path:
        return _process_product_variant(operation, product_data)

    local_timestamp = _payload_timestamp(operation, product_data)
    product = _model_by_pk(Product, _first_value(product_data.get('server_id') or product_data.get('id')))
    sku = str(_first_value(product_data.get('sku') or product_data.get('product_sku')) or '').strip()
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
            name=_first_value(product_data.get('name') or product_data.get('new_product_name')) or 'Offline product',
            sku=sku or f"offline-{operation['local_uuid']}",
            category=_category_from_product_data(product_data),
            material=_first_value(product_data.get('material')) or '',
            pieces_per_dozen=_int_value(product_data.get('pieces_per_dozen'), 12),
            retail_price=_decimal_value(product_data.get('retail_price')),
            wholesale_price=_decimal_value(product_data.get('wholesale_price')),
        )
    else:
        product.name = _first_value(product_data.get('name')) or product.name
        if sku:
            product.sku = sku
        category = _category_from_product_data(product_data)
        if category is not None:
            product.category = category
        product.material = _first_value(product_data.get('material')) or product.material
        product.pieces_per_dozen = _int_value(product_data.get('pieces_per_dozen'), product.pieces_per_dozen)
        product.retail_price = _decimal_value(product_data.get('retail_price'), product.retail_price)
        product.wholesale_price = _decimal_value(product_data.get('wholesale_price'), product.wholesale_price)

    update_fields = [
        'name', 'sku', 'category', 'material', 'pieces_per_dozen',
        'retail_price', 'wholesale_price', 'updated_at',
    ]
    if _save_payload_file(product, 'image', _file_payload(product_data, 'image', index=0)):
        update_fields.append('image')
    product.save(update_fields=[field for field in update_fields if hasattr(product, field)])

    _sync_initial_variant_and_stock(product, product_data, user)
    if operation.get('operation_type') != 'create':
        _sync_product_variants_from_update(product, product_data)
        _sync_product_stock_from_update(product, product_data, user)
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


def _first_int_from_path(path):
    for part in str(path or '').split('/'):
        if _is_int(part):
            return part
    return None


def _supplier_from_purchase_data(data):
    supplier = _related_by_id(Supplier, data.get('supplier') or data.get('server_id') or data.get('id'))
    name = (
        _first_value(data.get('new_supplier_name'))
        or _first_value(data.get('name'))
        or _first_value(data.get('supplier_name'))
    )
    phone = _first_value(data.get('new_supplier_phone')) or _first_value(data.get('phone')) or ''
    if supplier is None and phone:
        supplier = Supplier.objects.filter(phone=str(phone).strip()).order_by('-created_at').first()
    if supplier is None and name:
        supplier = Supplier.objects.filter(name=str(name).strip()).order_by('-created_at').first()
    if supplier is None and name:
        supplier = Supplier.objects.create(
            name=str(name).strip(),
            phone=str(phone).strip() or None,
            email=_first_value(data.get('email')) or '',
            address=_first_value(data.get('address')) or '',
            company_name=_first_value(data.get('company_name')) or '',
            notes=_first_value(data.get('notes')) or '',
            is_active=True,
        )
    if supplier is not None and (data.get('name') or data.get('phone') or data.get('company_name')):
        supplier.name = _first_value(data.get('name'), supplier.name) or supplier.name
        supplier.phone = _first_value(data.get('phone'), supplier.phone) or supplier.phone
        supplier.email = _first_value(data.get('email'), supplier.email) or supplier.email
        supplier.address = _first_value(data.get('address'), supplier.address) or supplier.address
        supplier.company_name = _first_value(data.get('company_name'), supplier.company_name) or supplier.company_name
        supplier.notes = _first_value(data.get('notes'), supplier.notes) or supplier.notes
        supplier.is_active = _bool_value(data.get('is_active'), True)
        supplier.save(update_fields=['name', 'phone', 'email', 'address', 'company_name', 'notes', 'is_active', 'updated_at'])
    return supplier


def _purchase_category(data):
    category = _related_by_id(Category, data.get('new_category') or data.get('category'))
    name = _first_value(data.get('new_category_name')) or ''
    if category is None and name:
        category, _ = Category.objects.get_or_create(name=name, defaults={'is_active': True})
    return category


def _purchase_color(data):
    color = _related_by_id(Color, data.get('new_color') or data.get('color'))
    name = _first_value(data.get('new_color_name')) or ''
    if color is None and name:
        color, _ = Color.objects.get_or_create(name=name)
    return color


def _purchase_size(data):
    size = _related_by_id(Size, data.get('new_size') or data.get('size'))
    name = _first_value(data.get('new_size_name')) or ''
    if size is None and name:
        size, _ = Size.objects.get_or_create(name=name, defaults={'sort_order': 0})
    return size


def _purchase_variant_from_data(data):
    variant = _related_by_id(ProductVariant, data.get('product_variant') or data.get('variant_id'))
    if variant:
        return variant

    name = str(_first_value(data.get('new_product_name')) or '').strip()
    sku = str(_first_value(data.get('new_product_sku')) or '').strip()
    if not name or not sku:
        raise ValidationError('Cannot sync purchase without a product variant')
    product = Product.objects.filter(sku=sku).first()
    if product is None:
        product = Product.objects.create(
            name=name,
            sku=sku,
            category=_purchase_category(data),
            pieces_per_dozen=_int_value(data.get('pieces_per_dozen'), 12),
            retail_price=_decimal_value(data.get('retail_price')),
            wholesale_price=_decimal_value(data.get('wholesale_price')),
        )
    color = _purchase_color(data)
    size = _purchase_size(data)
    variant = ProductVariant.objects.filter(product=product, color=color, size=size).first()
    if variant is None:
        variant = ProductVariant.objects.create(
            product=product,
            color=color,
            size=size,
            variant_sku=_offline_variant_sku(product, color, size),
            cost_price=_decimal_value(data.get('unit_cost')),
            sale_price=_decimal_value(data.get('retail_price')),
            retail_price=_decimal_value(data.get('retail_price')),
            wholesale_price=_decimal_value(data.get('wholesale_price')),
        )
    return variant


def _purchase_items(data):
    items = []
    for item in _json_items(data.get('items_json')):
        variant = _related_by_id(ProductVariant, item.get('product_variant_id') or item.get('variant_id'))
        if variant is None:
            variant = _purchase_variant_from_data(data)
        items.append({
            'product_variant': variant,
            'quantity': int(item.get('quantity') or 0),
            'unit_cost': Decimal(str(item.get('unit_cost') or 0)),
        })
    if items:
        return items
    return [{
        'product_variant': _purchase_variant_from_data(data),
        'quantity': _int_value(data.get('quantity'), 1),
        'unit_cost': _decimal_value(data.get('unit_cost')),
    }]


@transaction.atomic
def process_purchase(operation, user):
    payload = operation.get('payload') or {}
    data = payload.get('purchase') or _form_payload(operation)
    path = payload.get('original_url') or ''

    if '/purchases/orders/ajax/quick-create-supplier/' in path:
        supplier = _supplier_from_purchase_data(data)
        if supplier is None:
            raise ValidationError('Cannot sync supplier without a name')
        return response_success(operation['local_uuid'], supplier.pk, 'Supplier', resolution='local_applied')

    if '/purchases/orders/ajax/quick-create-product/' in path:
        variant = _purchase_variant_from_data(data)
        return response_success(operation['local_uuid'], variant.pk, 'ProductVariant', resolution='local_applied')

    if '/purchases/suppliers/' in path and '/raw-purchase/' not in path:
        supplier = _supplier_from_purchase_data(data)
        if supplier is None:
            raise ValidationError('Cannot sync supplier without a name')
        if operation.get('operation_type') == 'delete':
            supplier.is_active = False
            supplier.save(update_fields=['is_active', 'updated_at'])
            return response_success(operation['local_uuid'], supplier.pk, 'Supplier', resolution='local_deleted')
        return response_success(operation['local_uuid'], supplier.pk, 'Supplier', resolution='local_applied')

    if '/purchases/orders/return/' in path:
        movement = create_purchase_return(
            supplier=_related_by_id(Supplier, data.get('supplier')),
            product_variant=_related_by_id(ProductVariant, data.get('product_variant')),
            warehouse=_related_by_id(Warehouse, data.get('warehouse')),
            quantity=_int_value(data.get('quantity'), 1),
            unit_cost=_decimal_value(data.get('unit_cost')),
            user=user,
            notes=_first_value(data.get('notes')) or '',
        )
        return response_success(operation['local_uuid'], movement.pk, 'StockMovement', resolution='local_applied')

    order_id = data.get('server_id') or data.get('id') or _first_int_from_path(path)
    purchase_order = _model_by_pk(PurchaseOrder, order_id)
    if '/pay/' in path:
        if purchase_order is None:
            raise ValidationError('Cannot sync supplier payment without a purchase order')
        tx = pay_supplier(
            purchase_order=purchase_order,
            cash_account=_related_by_id(CashAccount, data.get('cash_account')),
            amount=_decimal_value(data.get('amount')),
            user=user,
            notes=_first_value(data.get('notes')) or '',
        )
        return response_success(operation['local_uuid'], tx.pk, 'PaymentTransaction', resolution='local_applied')

    if '/cancel/' in path or operation.get('operation_type') == 'delete':
        if purchase_order is None:
            return response_success(operation['local_uuid'], None, 'PurchaseOrder', resolution='server_deleted')
        cancel_purchase_order(purchase_order=purchase_order, user=user)
        return response_success(operation['local_uuid'], purchase_order.pk, 'PurchaseOrder', resolution='local_deleted')

    supplier = _supplier_from_purchase_data(data)
    if supplier is None:
        raise ValidationError('Cannot sync purchase without a supplier')
    items = _purchase_items(data)
    purchase_order = create_purchase_order(
        supplier=supplier,
        status=PurchaseOrder.STATUS_ORDERED,
        order_date=_date_value(data.get('order_date')),
        expected_date=_date_value(data.get('expected_date')),
        notes=_first_value(data.get('notes')) or '',
        items=items,
        user=user,
    )
    warehouse = _related_by_id(Warehouse, data.get('warehouse'))
    if warehouse:
        receive_purchase_order_items(
            purchase_order=purchase_order,
            warehouse=warehouse,
            received_items={item.pk: item.quantity for item in purchase_order.items.all()},
            user=user,
            note=_first_value(data.get('notes')) or '',
        )
    cash_account = _related_by_id(CashAccount, data.get('cash_account'))
    paid_amount = _decimal_value(data.get('paid_amount'))
    if cash_account and paid_amount > 0:
        pay_supplier(
            purchase_order=purchase_order,
            cash_account=cash_account,
            amount=paid_amount,
            user=user,
            notes=_first_value(data.get('notes')) or f'Offline purchase {purchase_order.purchase_number}',
        )
    return response_success(operation['local_uuid'], purchase_order.pk, 'PurchaseOrder', resolution='local_applied')


PROCESSORS = {
    'customer': process_customer,
    'order': process_order,
    'payment': process_payment,
    'return': process_return,
    'stock': process_stock,
    'product': process_product,
    'driver_action': process_driver_action,
    'purchase': process_purchase,
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
