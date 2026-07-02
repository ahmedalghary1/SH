import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils.dateparse import parse_datetime

from customers.models import Customer
from customers.services import visible_customers_for_user
from finance.models import CashAccount
from inventory.models import Stock, Warehouse
from orders.models import Order
from products.models import Product, ProductVariant
from settings_app.models import CompanySettings

from .auth import method_not_allowed, token_required, user_payload
from .serializers import serialize_customer, serialize_order, serialize_product, serialize_stock, serialize_variant
from .services import process_operation


def ping_view(request):
    if request.method != 'GET':
        return method_not_allowed(['GET'])
    return JsonResponse({'status': 'ok'})


def _allowed_stock(user):
    stock = Stock.objects.select_related('warehouse', 'variant__product').filter(warehouse__is_active=True, variant__is_active=True)
    if getattr(user, 'is_sales', False):
        stock = stock.filter(warehouse__assigned_user=user)
    return stock


def _can_view_all_inventory(user):
    return bool(
        getattr(user, 'is_superuser', False)
        or getattr(user, 'is_manager', False)
        or getattr(user, 'is_director', False)
        or getattr(user, 'is_warehouse', False)
    )


def _allowed_products_and_variants(user):
    products = Product.objects.filter(is_active=True).select_related('category')
    variants = ProductVariant.objects.filter(is_active=True, product__is_active=True).select_related('product', 'color', 'size')
    if _can_view_all_inventory(user):
        return products, variants
    if getattr(user, 'is_sales', False):
        allowed_variant_ids = _allowed_stock(user).filter(quantity__gt=0).values('variant_id')
        variants = variants.filter(pk__in=allowed_variant_ids).distinct()
        products = products.filter(variants__in=variants).distinct()
        return products, variants
    return products.none(), variants.none()


def _allowed_orders(user):
    orders = Order.objects.select_related('customer', 'created_by').order_by('-created_at')
    if getattr(user, 'is_superuser', False) or getattr(user, 'is_manager', False) or getattr(user, 'is_director', False):
        return orders
    if getattr(user, 'is_sales', False):
        return orders.filter(created_by=user)
    if getattr(user, 'is_warehouse', False):
        return orders.exclude(status=Order.STATUS_DRAFT)
    return orders.none()


def _allowed_warehouses(user):
    warehouses = Warehouse.objects.filter(is_active=True).select_related('assigned_user').order_by('warehouse_type', 'name')
    if getattr(user, 'is_sales', False) and not getattr(user, 'is_superuser', False):
        return warehouses.filter(assigned_user=user)
    if _can_view_all_inventory(user):
        return warehouses
    return warehouses.none()


def _allowed_cash_accounts(user):
    accounts = CashAccount.objects.filter(is_active=True).select_related('assigned_user').order_by('account_type', 'name')
    if getattr(user, 'is_superuser', False) or getattr(user, 'is_manager', False) or getattr(user, 'is_director', False):
        return accounts
    if getattr(user, 'is_sales', False):
        return accounts.filter(assigned_user=user)
    return accounts.none()


def _bootstrap_payload(user):
    can_view_costs = bool(getattr(user, 'is_manager', False))
    products, variants = _allowed_products_and_variants(user)
    customers = visible_customers_for_user(user, Customer.objects.filter(is_active=True)).order_by('-created_at')
    company = CompanySettings.load()
    cash_account = CashAccount.get_default()
    return {
        'user': user_payload(user),
        'permissions': user_payload(user)['permissions'],
        'company': {
            'name': company.company_name,
            'phone': company.phone or '',
            'address': company.address or '',
            'invoice_notes': company.invoice_notes or '',
            'max_sales_discount_percentage': str(company.max_sales_discount_percentage),
        },
        'cash': {
            'balance': str(cash_account.balance),
            'name': cash_account.name,
        },
        'products': [serialize_product(product) for product in products],
        'variants': [serialize_variant(variant, can_view_costs=can_view_costs) for variant in variants],
        'customers': [serialize_customer(customer) for customer in customers],
        'orders': [serialize_order(order) for order in _allowed_orders(user)],
        'stock': [serialize_stock(stock) for stock in _allowed_stock(user)],
        'warehouses': [
            {
                'id': warehouse.pk,
                'name': warehouse.name,
                'warehouse_type': warehouse.warehouse_type,
                'assigned_user_id': warehouse.assigned_user_id,
            }
            for warehouse in _allowed_warehouses(user)
        ],
        'cash_accounts': [
            {
                'id': account.pk,
                'name': account.name,
                'account_type': account.account_type,
                'assigned_user_id': account.assigned_user_id,
                'balance': str(account.balance),
            }
            for account in _allowed_cash_accounts(user)
        ],
    }


@token_required
def bootstrap_view(request):
    if request.method != 'GET':
        return method_not_allowed(['GET'])
    return JsonResponse(_bootstrap_payload(request.sync_user))


@token_required
def changes_view(request):
    if request.method != 'GET':
        return method_not_allowed(['GET'])
    since_param = request.GET.get('since')
    since = parse_datetime(since_param) if since_param else None
    if since_param and since is None:
        return JsonResponse({'error': 'Invalid since datetime'}, status=400)
    payload = _bootstrap_payload(request.sync_user)
    if since:
        customers = visible_customers_for_user(
            request.sync_user,
            Customer.objects.filter(is_active=True, updated_at__gte=since),
        ).order_by('-updated_at')
        payload['customers'] = [serialize_customer(customer) for customer in customers]
        orders = Order.objects.select_related('customer', 'created_by').filter(updated_at__gte=since).order_by('-updated_at')
        if getattr(request.sync_user, 'is_sales', False):
            orders = orders.filter(created_by=request.sync_user)
        elif not getattr(request.sync_user, 'is_manager', False):
            orders = orders.none()
        payload['orders'] = [serialize_order(order) for order in orders]
    return JsonResponse(payload)


@token_required
def push_view(request):
    if request.method != 'POST':
        return method_not_allowed(['POST'])
    try:
        operations = json.loads(request.body.decode('utf-8') or '[]')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    if not isinstance(operations, list):
        return JsonResponse({'error': 'Expected a list of operations'}, status=400)
    results = []
    for operation in operations:
        if not isinstance(operation, dict):
            results.append({'local_uuid': '', 'status': 'failed', 'error': 'Operation must be an object'})
            continue
        if not operation.get('idempotency_key') or not operation.get('local_uuid'):
            results.append({'local_uuid': operation.get('local_uuid'), 'status': 'failed', 'error': 'Missing idempotency_key or local_uuid'})
            continue
        results.append(process_operation(operation, request.sync_user))
    return JsonResponse(results, safe=False)


def _read_operations(request):
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return None, JsonResponse({'error': 'Invalid JSON'}, status=400)
    if isinstance(payload, list):
        return payload, None
    if isinstance(payload, dict):
        return [payload], None
    return None, JsonResponse({'error': 'Expected an operation object or list'}, status=400)


def _browser_push(request, default_entity_type):
    if request.method != 'POST':
        return method_not_allowed(['POST'])
    operations, error_response = _read_operations(request)
    if error_response:
        return error_response
    results = []
    for operation in operations:
        if not isinstance(operation, dict):
            results.append({'local_uuid': '', 'status': 'failed', 'error': 'Operation must be an object'})
            continue
        operation.setdefault('entity_type', default_entity_type)
        if not operation.get('idempotency_key') or not operation.get('local_uuid'):
            results.append({'local_uuid': operation.get('local_uuid'), 'status': 'failed', 'error': 'Missing idempotency_key or local_uuid'})
            continue
        results.append(process_operation(operation, request.user))
    if len(results) == 1:
        return JsonResponse(results[0])
    return JsonResponse(results, safe=False)


@login_required
def browser_bootstrap_view(request):
    if request.method != 'GET':
        return method_not_allowed(['GET'])
    return JsonResponse(_bootstrap_payload(request.user))


@login_required
def browser_changes_view(request):
    if request.method != 'GET':
        return method_not_allowed(['GET'])
    since_param = request.GET.get('since')
    since = parse_datetime(since_param) if since_param else None
    if since_param and since is None:
        return JsonResponse({'error': 'Invalid since datetime'}, status=400)
    payload = _bootstrap_payload(request.user)
    if since:
        customers = visible_customers_for_user(
            request.user,
            Customer.objects.filter(is_active=True, updated_at__gte=since),
        ).order_by('-updated_at')
        payload['customers'] = [serialize_customer(customer) for customer in customers]
        orders = Order.objects.select_related('customer', 'created_by').filter(updated_at__gte=since).order_by('-updated_at')
        if getattr(request.user, 'is_sales', False):
            orders = orders.filter(created_by=request.user)
        elif not getattr(request.user, 'is_manager', False):
            orders = orders.none()
        payload['orders'] = [serialize_order(order) for order in orders]
    return JsonResponse(payload)


@login_required
def browser_sync_sales_view(request):
    return _browser_push(request, 'order')


@login_required
def browser_sync_products_view(request):
    return _browser_push(request, 'product')


@login_required
def browser_sync_stock_view(request):
    return _browser_push(request, 'stock')


@login_required
def browser_sync_customers_view(request):
    return _browser_push(request, 'customer')


@login_required
def browser_sync_cash_view(request):
    return _browser_push(request, 'payment')


@login_required
def browser_sync_returns_view(request):
    return _browser_push(request, 'return')


@login_required
def browser_sync_driver_actions_view(request):
    return _browser_push(request, 'driver_action')
