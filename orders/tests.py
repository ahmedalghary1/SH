from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts.models import User
from customers.models import Customer
from inventory.models import Stock, StockMovement, Warehouse
from products.models import Category, Color, Product, ProductVariant, Size

from .models import Order, OrderItem
from .services import cancel_order, confirm_order


class OrderStockServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='manager', password='pass', role='manager')
        category = Category.objects.create(name='تيشيرتات')
        color = Color.objects.create(name='أسود')
        size = Size.objects.create(name='M')
        product = Product.objects.create(
            name='Basic Cotton',
            sku='BC-001',
            category=category,
            retail_price=Decimal('300.00'),
            wholesale_price=Decimal('220.00'),
        )
        self.variant = ProductVariant.objects.create(
            product=product,
            color=color,
            size=size,
            variant_sku='BC-001-BLK-M',
        )
        self.warehouse = Warehouse.objects.create(name='المخزن الرئيسي', warehouse_type='main')
        self.customer = Customer.objects.create(name='عميل اختبار', customer_type='b2c', phone='01000000000', created_by=self.user)
        Stock.objects.create(warehouse=self.warehouse, variant=self.variant, quantity=5, min_quantity=1)
        self.order = Order.objects.create(
            order_number='ORD-TEST-001',
            order_type='b2c',
            customer=self.customer,
            warehouse=self.warehouse,
            created_by=self.user,
        )
        OrderItem.objects.create(
            order=self.order,
            variant=self.variant,
            quantity=3,
            unit_price=Decimal('300.00'),
            total=Decimal('900.00'),
        )

    def test_confirm_order_decreases_stock_and_records_sale(self):
        confirm_order(order=self.order, user=self.user)
        stock = Stock.objects.get(warehouse=self.warehouse, variant=self.variant)
        self.order.refresh_from_db()

        self.assertEqual(stock.quantity, 2)
        self.assertEqual(self.order.status, Order.STATUS_CONFIRMED)
        self.assertTrue(StockMovement.objects.filter(movement_type=StockMovement.TYPE_SALE, quantity=3).exists())

    def test_confirm_order_rejects_unavailable_quantity(self):
        self.order.items.update(quantity=8, total=Decimal('2400.00'))

        with self.assertRaises(ValidationError):
            confirm_order(order=self.order, user=self.user)

        stock = Stock.objects.get(warehouse=self.warehouse, variant=self.variant)
        self.assertEqual(stock.quantity, 5)

    def test_cancel_confirmed_order_returns_stock(self):
        confirm_order(order=self.order, user=self.user)
        cancel_order(order=self.order, user=self.user)
        stock = Stock.objects.get(warehouse=self.warehouse, variant=self.variant)
        self.order.refresh_from_db()

        self.assertEqual(stock.quantity, 5)
        self.assertEqual(self.order.status, Order.STATUS_CANCELLED)
        self.assertTrue(StockMovement.objects.filter(movement_type=StockMovement.TYPE_RETURN, quantity=3).exists())

# Create your tests here.
