from customers.models import Customer
from inventory.models import Stock
from orders.models import Order
from products.models import Product, ProductVariant


def serialize_product(product: Product):
    return {
        'id': product.pk,
        'name': product.name,
        'sku': product.sku,
        'category': product.category.name if product.category else '',
        'pieces_per_dozen': product.pieces_per_dozen,
        'retail_price': str(product.retail_price),
        'wholesale_price': str(product.wholesale_price),
        'image_url': product.image.url if product.image else '',
        'is_active': product.is_active,
        'created_at': product.created_at.isoformat() if product.created_at else '',
        'updated_at': product.updated_at.isoformat() if getattr(product, 'updated_at', None) else product.created_at.isoformat() if product.created_at else '',
    }


def serialize_variant(variant: ProductVariant, *, can_view_costs=False):
    return {
        'id': variant.pk,
        'product_id': variant.product_id,
        'product_name': variant.product.name,
        'product_sku': variant.product.sku,
        'color': variant.color.name if variant.color else '',
        'size': variant.size.name if variant.size else '',
        'variant_sku': variant.variant_sku,
        'barcode': variant.barcode or '',
        'sale_price': str(variant.sale_price),
        'retail_price': str(variant.retail_price or variant.sale_price),
        'wholesale_price': str(variant.wholesale_price or variant.sale_price),
        'cost_price': str(variant.cost_price) if can_view_costs else '0',
        'image_url': variant.image.url if variant.image else '',
        'pieces_per_dozen': variant.product.pieces_per_dozen,
        'is_active': variant.is_active,
        'updated_at': variant.updated_at.isoformat() if getattr(variant, 'updated_at', None) else '',
    }


def serialize_stock(stock: Stock):
    return {
        'variant_id': stock.variant_id,
        'warehouse_id': stock.warehouse_id,
        'warehouse_name': stock.warehouse.name,
        'quantity': stock.quantity,
        'min_quantity': stock.min_quantity,
        'updated_at': stock.updated_at.isoformat() if getattr(stock, 'updated_at', None) else '',
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
        'created_at': customer.created_at.isoformat() if customer.created_at else '',
        'updated_at': customer.updated_at.isoformat() if getattr(customer, 'updated_at', None) else customer.created_at.isoformat() if customer.created_at else '',
    }


def serialize_order(order: Order):
    return {
        'id': order.pk,
        'local_uuid': f'server-order-{order.pk}',
        'order_number': order.order_number,
        'customer_id': order.customer_id,
        'customer_local_uuid': f'server-{order.customer_id}' if order.customer_id else '',
        'document_type': order.document_type,
        'order_type': order.order_type,
        'status': order.status,
        'payment_status': order.payment_status,
        'payment_method': order.payment_method,
        'subtotal': str(order.subtotal),
        'discount': str(order.discount),
        'total': str(order.total),
        'paid_amount': str(order.paid_amount),
        'remaining_amount': str(order.remaining_amount),
        'notes': order.notes or '',
        'created_by_id': order.created_by_id,
        'created_by_name': order.created_by.get_full_name() or order.created_by.username if order.created_by else '',
        'created_at': order.created_at.isoformat() if order.created_at else '',
        'updated_at': order.updated_at.isoformat() if order.updated_at else '',
    }
