from customers.models import Customer
from inventory.models import Stock
from products.models import Product, ProductVariant


def serialize_product(product: Product):
    return {
        'id': product.pk,
        'name': product.name,
        'sku': product.sku,
        'category': product.category.name if product.category else '',
        'is_active': product.is_active,
        'updated_at': product.created_at.isoformat() if product.created_at else '',
    }


def serialize_variant(variant: ProductVariant, *, can_view_costs=False):
    return {
        'id': variant.pk,
        'product_id': variant.product_id,
        'color': variant.color.name if variant.color else '',
        'size': variant.size.name if variant.size else '',
        'variant_sku': variant.variant_sku,
        'barcode': variant.barcode or '',
        'sale_price': str(variant.sale_price),
        'cost_price': str(variant.cost_price) if can_view_costs else '0',
        'image_url': variant.image.url if variant.image else '',
        'is_active': variant.is_active,
        'updated_at': '',
    }


def serialize_stock(stock: Stock):
    return {
        'variant_id': stock.variant_id,
        'warehouse_id': stock.warehouse_id,
        'warehouse_name': stock.warehouse.name,
        'quantity': stock.quantity,
        'min_quantity': stock.min_quantity,
        'updated_at': '',
    }


def serialize_customer(customer: Customer):
    return {
        'id': customer.pk,
        'local_uuid': f'server-{customer.pk}',
        'name': customer.name,
        'phone': customer.phone,
        'whatsapp': customer.whatsapp or '',
        'customer_type': customer.customer_type,
        'address': customer.address or '',
        'credit_limit': str(customer.credit_limit),
        'opening_balance': str(customer.opening_balance),
        'updated_at': customer.created_at.isoformat() if customer.created_at else '',
    }
