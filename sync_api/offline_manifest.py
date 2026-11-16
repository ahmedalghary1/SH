"""Permission-filtered offline screen manifest."""
from urllib.parse import urlsplit
from django.urls import resolve, Resolver404
from accounts.permissions import has_role

CANDIDATES = ['/',
 '/products/',
 '/products/create/',
 '/products/representative/create/',
 '/products/categories/',
 '/products/categories/create/',
 '/products/sizes/',
 '/products/sizes/create/',
 '/products/colors/',
 '/products/colors/create/',
 '/products/variants/create/',
 '/products/bulk-price-update/',
 '/inventory/stock/',
 '/inventory/movements/',
 '/inventory/movements/in/',
 '/inventory/movements/out/',
 '/inventory/movements/transfer/',
 '/inventory/movements/representative-issue/',
 '/inventory/movements/representative-return/',
 '/inventory/movements/adjustment/',
 '/inventory/warehouses/',
 '/inventory/warehouses/create/',
 '/customers/',
 '/customers/simple/create/',
 '/customers/list/',
 '/customers/create/',
 '/orders/create/',
 '/orders/',
 '/orders/quotes/',
 '/invoices/',
 '/finance/cash/',
 '/finance/shift/',
 '/finance/accounts/',
 '/finance/accounts/create/',
 '/finance/transactions/',
 '/finance/transactions/?type=customer_payment',
 '/finance/transactions/?type=expense',
 '/finance/transactions/expense/',
 '/finance/transactions/collection/',
 '/finance/statements/customer/',
 '/finance/transactions/supplier-payment/',
 '/finance/transactions/transfer/',
 '/returns/',
 '/returns/simple/',
 '/returns/exchange/',
 '/returns/create/',
 '/sales-reps/',
 '/sales-reps/assignments/',
 '/sales-reps/assign/',
 '/sales-reps/return-stock/',
 '/sales-reps/record-sale/',
 '/sales-reps/collection/',
 '/sales-reps/handover/',
 '/sales-reps/statement/',
 '/purchases/suppliers/simple/',
 '/purchases/suppliers/simple/create/',
 '/purchases/suppliers/',
 '/purchases/suppliers/create/',
 '/purchases/suppliers/raw-purchase/',
 '/purchases/orders/',
 '/purchases/orders/create/',
 '/purchases/orders/return/',
 '/reports/',
 '/settings/']


def offline_pages(user):
    from accounts.middleware import RepresentativeAccessMiddleware
    pages = []
    for url in [*CANDIDATES, '/orders/create/?document=quote']:
        if url in {'/settings/', '/reports/'}:
            continue
        try:
            match = resolve(urlsplit(url).path)
        except Resolver404:
            continue
        if user.role == 'sales' and not user.is_superuser:
            if match.view_name not in RepresentativeAccessMiddleware.allowed_views:
                continue
        view = getattr(match.func, 'view_class', None)
        if view and hasattr(view, 'allowed_roles') and not has_role(user, *view.allowed_roles):
            continue
        pages.append(url)
    return pages


def offline_detail_urls(user, payload):
    from accounts.middleware import RepresentativeAccessMiddleware
    urls = [f'/orders/{row["id"]}/' for row in payload['orders']]
    urls += [f'/invoices/{row["invoice_id"]}/' for row in payload['orders'] if row['invoice_id']]
    urls += [f'/products/{row["id"]}/' for row in payload['products']]
    urls += [f'/customers/simple/{row["id"]}/' for row in payload['customers']]
    urls += [f'/customers/{row["id"]}/' for row in payload['customers']]
    result = []
    for url in urls:
        match = resolve(url)
        if user.role == 'sales' and not user.is_superuser and match.view_name not in RepresentativeAccessMiddleware.allowed_views:
            continue
        view = getattr(match.func, 'view_class', None)
        if view and hasattr(view, 'allowed_roles') and not has_role(user, *view.allowed_roles):
            continue
        result.append(url)
    return result
