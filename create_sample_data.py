"""
Create sample data for the project
"""
import os
import sys
import django

# Set UTF-8 encoding for stdout
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from decimal import Decimal
from django.contrib.auth import get_user_model
from django.utils import timezone
from products.models import Product, ProductVariant, Color, Size, Category
from customers.models import Customer
from inventory.models import Warehouse, Stock
from orders.models import Order, OrderItem
from returns.models import SalesReturn, SalesReturnItem

User = get_user_model()

def create_sample_data():
    """Create sample data for the project"""
    
    # Create users
    print("Creating users...")
    manager, _ = User.objects.get_or_create(
        username='manager',
        defaults={
            'role': 'manager',
            'is_superuser': True,
            'is_staff': True,
        }
    )
    manager.set_password('admin123')
    manager.save()
    
    sales_user, _ = User.objects.get_or_create(
        username='sales',
        defaults={
            'role': 'sales',
            'is_staff': True,
        }
    )
    sales_user.set_password('sales123')
    sales_user.save()
    
    warehouse_user, _ = User.objects.get_or_create(
        username='warehouse',
        defaults={
            'role': 'warehouse',
            'is_staff': True,
        }
    )
    warehouse_user.set_password('warehouse123')
    warehouse_user.save()
    
    # Create categories
    print("Creating categories...")
    category_shirts, _ = Category.objects.get_or_create(
        name='قمصان',
        defaults={'is_active': True}
    )
    category_pants, _ = Category.objects.get_or_create(
        name='بنطال',
        defaults={'is_active': True}
    )
    category_dresses, _ = Category.objects.get_or_create(
        name='فساتين',
        defaults={'is_active': True}
    )
    
    # Create colors
    print("Creating colors...")
    color_black, _ = Color.objects.get_or_create(
        name='أسود',
        defaults={'hex_code': '#000000'}
    )
    color_white, _ = Color.objects.get_or_create(
        name='أبيض',
        defaults={'hex_code': '#FFFFFF'}
    )
    color_blue, _ = Color.objects.get_or_create(
        name='أزرق',
        defaults={'hex_code': '#0000FF'}
    )
    color_red, _ = Color.objects.get_or_create(
        name='أحمر',
        defaults={'hex_code': '#FF0000'}
    )
    color_green, _ = Color.objects.get_or_create(
        name='أخضر',
        defaults={'hex_code': '#00FF00'}
    )
    
    # Create sizes
    print("Creating sizes...")
    size_s, _ = Size.objects.get_or_create(
        name='S',
        defaults={'sort_order': 1}
    )
    size_m, _ = Size.objects.get_or_create(
        name='M',
        defaults={'sort_order': 2}
    )
    size_l, _ = Size.objects.get_or_create(
        name='L',
        defaults={'sort_order': 3}
    )
    size_xl, _ = Size.objects.get_or_create(
        name='XL',
        defaults={'sort_order': 4}
    )
    size_xxl, _ = Size.objects.get_or_create(
        name='XXL',
        defaults={'sort_order': 5}
    )
    
    # Create warehouses
    print("Creating warehouses...")
    warehouse_main, _ = Warehouse.objects.get_or_create(
        name='المخزن الرئيسي',
        defaults={
            'warehouse_type': Warehouse.TYPE_MAIN,
            'address': 'الرياض - حي الملز',
            'is_active': True,
            'assigned_user': warehouse_user,
        }
    )
    
    warehouse_branch, _ = Warehouse.objects.get_or_create(
        name='مخزن الفرع',
        defaults={
            'warehouse_type': Warehouse.TYPE_STORE,
            'address': 'الرياض - حي النخيل',
            'is_active': True,
            'assigned_user': warehouse_user,
        }
    )
    
    # Create customers
    print("Creating customers...")
    customer1, _ = Customer.objects.get_or_create(
        phone='0501234567',
        defaults={
            'name': 'أحمد محمد',
            'address': 'الرياض - حي الملز',
            'customer_type': Customer.TYPE_B2C,
            'credit_limit': Decimal('10000'),
            'opening_balance': Decimal('0'),
        }
    )
    
    customer2, _ = Customer.objects.get_or_create(
        phone='0509876543',
        defaults={
            'name': 'فاطمة علي',
            'address': 'الرياض - حي النخيل',
            'customer_type': Customer.TYPE_B2C,
            'credit_limit': Decimal('5000'),
            'opening_balance': Decimal('0'),
        }
    )
    
    customer3, _ = Customer.objects.get_or_create(
        phone='0551112233',
        defaults={
            'name': 'محمد عبدالله',
            'address': 'الرياض - حي العليا',
            'customer_type': Customer.TYPE_B2C,
            'credit_limit': Decimal('15000'),
            'opening_balance': Decimal('0'),
        }
    )
    
    # Create products
    print("Creating products...")
    products_data = [
        {
            'name': 'قميص كلاسيك أسود',
            'sku': 'SHIRT-BLK-001',
            'category': category_shirts,
            'description': 'قميص كلاسيك أسود أنيق',
            'retail_price': Decimal('150'),
            'wholesale_price': Decimal('100'),
        },
        {
            'name': 'قميص كلاسيك أبيض',
            'sku': 'SHIRT-WHT-002',
            'category': category_shirts,
            'description': 'قميص كلاسيك أبيض أنيق',
            'retail_price': Decimal('150'),
            'wholesale_price': Decimal('100'),
        },
        {
            'name': 'بنطال جينز أزرق',
            'sku': 'PANTS-BLU-001',
            'category': category_pants,
            'description': 'بنطال جينز أزرق عالي الجودة',
            'retail_price': Decimal('250'),
            'wholesale_price': Decimal('180'),
        },
        {
            'name': 'بنطال رسمي أسود',
            'sku': 'PANTS-BLK-002',
            'category': category_pants,
            'description': 'بنطال رسمي أسود أنيق',
            'retail_price': Decimal('200'),
            'wholesale_price': Decimal('150'),
        },
        {
            'name': 'فستان سهرة أحمر',
            'sku': 'DRESS-RED-001',
            'category': category_dresses,
            'description': 'فستان سهرة أحمر فاخر',
            'retail_price': Decimal('500'),
            'wholesale_price': Decimal('350'),
        },
    ]
    
    colors = [color_black, color_white, color_blue, color_red]
    sizes = [size_s, size_m, size_l, size_xl]
    
    for product_data in products_data:
        product, created = Product.objects.get_or_create(
            sku=product_data['sku'],
            defaults={
                'name': product_data['name'],
                'category': product_data['category'],
                'description': product_data['description'],
                'retail_price': product_data['retail_price'],
                'wholesale_price': product_data['wholesale_price'],
                'is_active': True,
            }
        )
        
        if created:
            # Create variants for the product
            for color in colors:
                for size in sizes:
                    variant_sku = f"{product_data['sku']}-{color.name}-{size.name}"
                    ProductVariant.objects.get_or_create(
                        variant_sku=variant_sku,
                        defaults={
                            'product': product,
                            'color': color,
                            'size': size,
                            'cost_price': product_data['wholesale_price'] * Decimal('0.6'),
                            'sale_price': product_data['retail_price'],
                            'is_active': True,
                        }
                    )
    
    # Create stock for products
    print("Creating stock for products...")
    variants = ProductVariant.objects.filter(is_active=True)
    for variant in variants[:20]:  # Create stock for first 20 variants
        Stock.objects.get_or_create(
            variant=variant,
            warehouse=warehouse_main,
            defaults={
                'quantity': 50,
            }
        )
    
    # Create sample orders
    print("Creating sample orders...")
    if not Order.objects.exists():
        order1 = Order.objects.create(
            order_number='INV-20260610-0001',
            customer=customer1,
            created_by=sales_user,
            status='completed',
            total=Decimal('300'),
            paid_amount=Decimal('300'),
        )
        
        # Add items to the order
        variant1 = ProductVariant.objects.filter(product__sku='SHIRT-BLK-001').first()
        variant2 = ProductVariant.objects.filter(product__sku='PANTS-BLU-001').first()
        
        if variant1:
            OrderItem.objects.create(
                order=order1,
                variant=variant1,
                quantity=2,
                unit_price=variant1.sale_price,
                total=variant1.sale_price * 2,
            )
        
        if variant2:
            OrderItem.objects.create(
                order=order1,
                variant=variant2,
                quantity=1,
                unit_price=variant2.sale_price,
                total=variant2.sale_price,
            )
        
        # Create sample return
        print("Creating sample return...")
        sales_return = SalesReturn.objects.create(
            order=order1,
            customer=customer1,
            return_type=SalesReturn.TYPE_PARTIAL_RETURN,
            status=SalesReturn.STATUS_COMPLETED,
            refund_amount=Decimal('150'),
            created_by=sales_user,
            reason='المنتج لا يناسب العميل',
        )
        
        if variant1:
            SalesReturnItem.objects.create(
                sales_return=sales_return,
                original_order_item=order1.items.first(),
                product_variant=variant1,
                quantity=1,
                condition=SalesReturnItem.CONDITION_GOOD,
                refund_amount=Decimal('150'),
            )
    
    print("Sample data created successfully!")
    print("\nLogin credentials:")
    print("Manager: username='manager', password='admin123'")
    print("Sales: username='sales', password='sales123'")
    print("Warehouse: username='warehouse', password='warehouse123'")

if __name__ == '__main__':
    create_sample_data()
