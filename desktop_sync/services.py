import json
from decimal import Decimal
from urllib import error, request

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from customers.models import Customer
from inventory.models import Stock, Warehouse
from orders.models import Order
from products.models import Category, Color, Product, ProductVariant, Size

from .models import DesktopSyncConfig, SyncEntityMap, SyncOutbox
from .state import importing_from_server


class SyncError(Exception):
    pass


def _json_request(config, path, *, method='GET', payload=None, token=None, timeout=20):
    url = config.normalized_api_url + path.lstrip('/')
    data = None
    headers = {'Accept': 'application/json'}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    auth_token = token if token is not None else config.token
    if auth_token:
        headers['Authorization'] = f'Bearer {auth_token}'
    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode('utf-8')
            return json.loads(raw or '{}')
    except error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')
        raise SyncError(f'HTTP {exc.code}: {detail}') from exc
    except error.URLError as exc:
        raise SyncError(str(exc.reason)) from exc
    except json.JSONDecodeError as exc:
        raise SyncError('Remote API returned invalid JSON') from exc


def login_remote(username, password, remote_api_url=None):
    config = DesktopSyncConfig.load()
    if remote_api_url:
        config.remote_api_url = remote_api_url
    payload = {'username': username, 'password': password, 'device_id': config.device_id}
    data = _json_request(config, 'auth/login/', method='POST', payload=payload, token='')
    token = data.get('token')
    if not token:
        raise SyncError(data.get('error') or 'Remote login failed')
    config.token = token
    config.username = username
    config.last_error = ''
    config.save(update_fields=['remote_api_url', 'token', 'username', 'last_error', 'updated_at'])
    _ensure_local_user(data.get('user') or {})
    return data


def _ensure_local_user(user_data):
    if not user_data:
        return None
    User = get_user_model()
    user, _ = User.objects.update_or_create(
        pk=user_data.get('id'),
        defaults={
            'username': user_data.get('username') or f"remote-{user_data.get('id')}",
            'first_name': user_data.get('full_name') or '',
            'role': user_data.get('role') or getattr(User, 'ROLE_SALES', 'sales'),
            'is_active': True,
        },
    )
    user.set_unusable_password()
    user.save(update_fields=['password'])
    return user


def _decimal(value):
    return Decimal(str(value or 0))


def _map(entity_type, local_object_id, server_object_id='', local_uuid='', server_origin=False):
    local_uuid = local_uuid or f'{entity_type}-{local_object_id}'
    obj, _ = SyncEntityMap.objects.update_or_create(
        entity_type=entity_type,
        local_object_id=str(local_object_id),
        defaults={
            'local_uuid': local_uuid,
            'server_object_id': str(server_object_id or ''),
            'is_server_origin': server_origin,
        },
    )
    return obj


def _server_id(entity_type, local_object_id):
    mapped = SyncEntityMap.objects.filter(entity_type=entity_type, local_object_id=str(local_object_id)).first()
    if mapped and mapped.server_object_id:
        return mapped.server_object_id
    return str(local_object_id)


def _local_uuid(entity_type, local_object_id):
    mapped = SyncEntityMap.objects.filter(entity_type=entity_type, local_object_id=str(local_object_id)).first()
    if mapped:
        return mapped.local_uuid
    mapped = _map(entity_type, local_object_id, local_uuid=f'{entity_type}-{local_object_id}')
    return mapped.local_uuid


@transaction.atomic
def apply_bootstrap(payload):
    with importing_from_server():
        user = _ensure_local_user(payload.get('user') or {})
        for product_data in payload.get('products', []):
            category = None
            if product_data.get('category'):
                category, _ = Category.objects.get_or_create(name=product_data['category'])
            Product.objects.update_or_create(
                pk=product_data['id'],
                defaults={
                    'name': product_data.get('name') or '',
                    'sku': product_data.get('sku') or f"remote-product-{product_data['id']}",
                    'category': category,
                    'is_active': bool(product_data.get('is_active', True)),
                },
            )
        for variant_data in payload.get('variants', []):
            color = None
            size = None
            if variant_data.get('color'):
                color, _ = Color.objects.get_or_create(name=variant_data['color'])
            if variant_data.get('size'):
                size, _ = Size.objects.get_or_create(name=variant_data['size'])
            ProductVariant.objects.update_or_create(
                pk=variant_data['id'],
                defaults={
                    'product_id': variant_data['product_id'],
                    'color': color,
                    'size': size,
                    'variant_sku': variant_data.get('variant_sku') or f"remote-variant-{variant_data['id']}",
                    'barcode': variant_data.get('barcode') or '',
                    'sale_price': _decimal(variant_data.get('sale_price')),
                    'retail_price': _decimal(variant_data.get('sale_price')),
                    'wholesale_price': _decimal(variant_data.get('sale_price')),
                    'cost_price': _decimal(variant_data.get('cost_price')),
                    'is_active': bool(variant_data.get('is_active', True)),
                },
            )
        for stock_data in payload.get('stock', []):
            warehouse, _ = Warehouse.objects.update_or_create(
                pk=stock_data['warehouse_id'],
                defaults={
                    'name': stock_data.get('warehouse_name') or f"Warehouse {stock_data['warehouse_id']}",
                    'warehouse_type': Warehouse.TYPE_REPRESENTATIVE if user and getattr(user, 'is_sales', False) else Warehouse.TYPE_STORE,
                    'assigned_user': user if user and getattr(user, 'is_sales', False) else None,
                    'is_active': True,
                },
            )
            Stock.objects.update_or_create(
                warehouse=warehouse,
                variant_id=stock_data['variant_id'],
                defaults={
                    'quantity': int(stock_data.get('quantity') or 0),
                    'min_quantity': int(stock_data.get('min_quantity') or 0),
                },
            )
        for customer_data in payload.get('customers', []):
            customer, _ = Customer.objects.update_or_create(
                pk=customer_data['id'],
                defaults={
                    'name': customer_data.get('name') or '',
                    'phone': customer_data.get('phone') or f"remote-{customer_data['id']}",
                    'whatsapp': customer_data.get('whatsapp') or '',
                    'customer_type': customer_data.get('customer_type') or Customer.TYPE_RETAIL,
                    'address': customer_data.get('address') or '',
                    'credit_limit': _decimal(customer_data.get('credit_limit')),
                    'opening_balance': _decimal(customer_data.get('opening_balance')),
                    'is_active': True,
                    'created_by': user,
                },
            )
            _map('customer', customer.pk, customer_data['id'], customer_data.get('local_uuid') or f"server-{customer.pk}", True)
        for order_data in payload.get('orders', []):
            customer = Customer.objects.filter(pk=order_data.get('customer_id')).first()
            order, _ = Order.objects.update_or_create(
                pk=order_data['id'],
                defaults={
                    'order_number': order_data.get('order_number') or f"REMOTE-{order_data['id']}",
                    'customer': customer,
                    'document_type': order_data.get('document_type') or Order.DOCUMENT_SALE,
                    'order_type': order_data.get('order_type') or Order.TYPE_B2C,
                    'status': order_data.get('status') or Order.STATUS_CONFIRMED,
                    'payment_status': order_data.get('payment_status') or Order.PAYMENT_UNPAID,
                    'payment_method': order_data.get('payment_method') or Order.METHOD_CASH,
                    'subtotal': _decimal(order_data.get('subtotal')),
                    'discount': _decimal(order_data.get('discount')),
                    'total': _decimal(order_data.get('total')),
                    'paid_amount': _decimal(order_data.get('paid_amount')),
                    'remaining_amount': _decimal(order_data.get('remaining_amount')),
                    'notes': order_data.get('notes') or '',
                    'created_by': user,
                },
            )
            _map('order', order.pk, order_data['id'], order_data.get('local_uuid') or f"server-order-{order.pk}", True)


def pull_remote():
    config = DesktopSyncConfig.load()
    if not config.token:
        raise SyncError('Desktop sync is not logged in to the remote API')
    path = 'sync/bootstrap/'
    if config.last_pull_at:
        path = f"sync/changes/?since={config.last_pull_at.isoformat()}"
    payload = _json_request(config, path)
    apply_bootstrap(payload)
    config.last_pull_at = timezone.now()
    config.last_error = ''
    config.save(update_fields=['last_pull_at', 'last_error', 'updated_at'])
    return payload


def build_customer_payload(customer):
    local_uuid = _local_uuid('customer', customer.pk)
    return {
        'customer': {
            'local_uuid': local_uuid,
            'name': customer.name,
            'phone': customer.phone,
            'whatsapp': customer.whatsapp or '',
            'customer_type': customer.customer_type,
            'address': customer.address or '',
            'credit_limit': str(customer.credit_limit),
            'opening_balance': str(customer.opening_balance),
        }
    }


def build_order_payload(order):
    customer_server_id = _server_id('customer', order.customer_id) if order.customer_id else ''
    customer_local_uuid = _local_uuid('customer', order.customer_id) if order.customer_id else ''
    return {
        'order': {
            'customer_server_id': customer_server_id,
            'customer_local_uuid': customer_local_uuid,
            'document_type': order.document_type,
            'order_type': order.order_type,
            'payment_method': order.payment_method,
            'paid_amount': str(order.paid_amount),
            'notes': order.notes or '',
            'discount': str(order.discount_amount or order.discount or 0),
        },
        'items': [
            {
                'variant_server_id': item.variant_id,
                'quantity': item.quantity,
                'unit_price': str(item.original_unit_price or item.unit_price),
                'discount': str(item.discount_amount or item.discount or 0),
            }
            for item in order.items.select_related('variant').all()
            if item.variant_id
        ],
    }


def refresh_outbox_payload(outbox):
    if outbox.entity_type == 'customer':
        obj = Customer.objects.filter(pk=outbox.local_object_id).first()
        outbox.payload = build_customer_payload(obj) if obj else outbox.payload
    elif outbox.entity_type == 'order':
        obj = Order.objects.filter(pk=outbox.local_object_id).prefetch_related('items').first()
        outbox.payload = build_order_payload(obj) if obj else outbox.payload
    outbox.save(update_fields=['payload', 'updated_at'])
    return outbox


def push_pending(limit=50):
    config = DesktopSyncConfig.load()
    if not config.token:
        raise SyncError('Desktop sync is not logged in to the remote API')
    pending = list(
        SyncOutbox.objects.filter(status__in=[SyncOutbox.STATUS_PENDING, SyncOutbox.STATUS_FAILED])
        .order_by('created_at')[:limit]
    )
    operations = []
    outbox_by_uuid = {}
    for outbox in pending:
        refresh_outbox_payload(outbox)
        operation = {
            'idempotency_key': outbox.idempotency_key,
            'device_id': config.device_id,
            'entity_type': outbox.entity_type,
            'operation_type': outbox.operation_type,
            'local_uuid': outbox.local_uuid,
            'payload': outbox.payload,
        }
        operations.append(operation)
        outbox_by_uuid[outbox.local_uuid] = outbox
    if not operations:
        return []
    results = _json_request(config, 'sync/push/', method='POST', payload=operations)
    for result in results:
        outbox = outbox_by_uuid.get(result.get('local_uuid'))
        if not outbox:
            continue
        outbox.attempts += 1
        outbox.response_json = result
        if result.get('status') == 'success':
            outbox.status = SyncOutbox.STATUS_SYNCED
            outbox.last_error = ''
            SyncEntityMap.objects.update_or_create(
                entity_type=outbox.entity_type,
                local_object_id=outbox.local_object_id,
                defaults={
                    'local_uuid': outbox.local_uuid,
                    'server_object_id': str(result.get('server_id') or ''),
                    'is_server_origin': False,
                },
            )
        elif result.get('status') == 'failed_conflict':
            outbox.status = SyncOutbox.STATUS_CONFLICT
            outbox.last_error = result.get('error') or ''
        else:
            outbox.status = SyncOutbox.STATUS_FAILED
            outbox.last_error = result.get('error') or ''
        outbox.save(update_fields=['attempts', 'response_json', 'status', 'last_error', 'updated_at'])
    config.last_push_at = timezone.now()
    config.last_error = ''
    config.save(update_fields=['last_push_at', 'last_error', 'updated_at'])
    return results


def sync_once():
    config = DesktopSyncConfig.load()
    try:
        pushed = push_pending()
        pulled = pull_remote()
        return {'pushed': pushed, 'pulled_counts': {k: len(v) for k, v in pulled.items() if isinstance(v, list)}}
    except Exception as exc:
        config.last_error = str(exc)
        config.save(update_fields=['last_error', 'updated_at'])
        raise
