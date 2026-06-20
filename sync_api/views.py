import json

from django.http import JsonResponse
from django.utils.dateparse import parse_datetime

from customers.models import Customer
from finance.models import CashAccount
from inventory.models import Stock
from orders.models import Order
from products.models import Product, ProductVariant
from settings_app.models import CompanySettings

from .auth import token_required, user_payload
from .serializers import serialize_customer, serialize_order, serialize_product, serialize_stock, serialize_variant
from .services import process_operation


def ping_view(request):
    return JsonResponse({'status': 'ok'})


def _allowed_stock(user):
    stock = Stock.objects.select_related('warehouse', 'variant__product').filter(warehouse__is_active=True, variant__is_active=True)
    if getattr(user, 'is_sales', False):
        stock = stock.filter(warehouse__assigned_user=user)
    return stock


def _allowed_orders(user):
    orders = Order.objects.select_related('customer', 'created_by').order_by('-created_at')
    if getattr(user, 'is_manager', False):
        return orders[:1000]
    if getattr(user, 'is_sales', False):
        return orders.filter(created_by=user)[:1000]
    return orders.none()


def _bootstrap_payload(user):
    can_view_costs = bool(getattr(user, 'is_manager', False))
    products = Product.objects.filter(is_active=True).select_related('category')
    variants = ProductVariant.objects.filter(is_active=True, product__is_active=True).select_related('product', 'color', 'size')
    customers = Customer.objects.filter(is_active=True).order_by('-created_at')[:1000]
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
    }


@token_required
def bootstrap_view(request):
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    return JsonResponse(_bootstrap_payload(request.sync_user))


@token_required
def changes_view(request):
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    since = parse_datetime(request.GET.get('since') or '') if request.GET.get('since') else None
    payload = _bootstrap_payload(request.sync_user)
    if since:
        payload['customers'] = [
            serialize_customer(customer)
            for customer in Customer.objects.filter(is_active=True, created_at__gte=since).order_by('-created_at')[:500]
        ]
        orders = Order.objects.select_related('customer', 'created_by').filter(updated_at__gte=since).order_by('-updated_at')
        if getattr(request.sync_user, 'is_sales', False):
            orders = orders.filter(created_by=request.sync_user)
        elif not getattr(request.sync_user, 'is_manager', False):
            orders = orders.none()
        payload['orders'] = [serialize_order(order) for order in orders[:500]]
    return JsonResponse(payload)


@token_required
def push_view(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    try:
        operations = json.loads(request.body.decode('utf-8') or '[]')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    if not isinstance(operations, list):
        return JsonResponse({'error': 'Expected a list of operations'}, status=400)
    results = []
    for operation in operations:
        if not operation.get('idempotency_key') or not operation.get('local_uuid'):
            results.append({'local_uuid': operation.get('local_uuid'), 'status': 'failed', 'error': 'Missing idempotency_key or local_uuid'})
            continue
        results.append(process_operation(operation, request.sync_user))
    return JsonResponse(results, safe=False)
