from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from accounts.models import User
from inventory.models import Stock, Warehouse, StockMovement
from products.models import Product, ProductVariant, Color, Size


class ConcurrencyTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username='manager', password='pass', role=User.ROLE_MANAGER)
        self.warehouse = Warehouse.objects.create(name='Main Warehouse', warehouse_type=Warehouse.TYPE_MAIN)
        self.color = Color.objects.create(name='Red')
        self.size = Size.objects.create(name='L')
        self.product = Product.objects.create(name='Test Product', sku='TEST001')
        self.variant = ProductVariant.objects.create(
            product=self.product,
            color=self.color,
            size=self.size,
            variant_sku='TEST001-RED-L',
            cost_price=Decimal('10.00'),
            sale_price=Decimal('20.00')
        )
        self.stock = Stock.objects.create(
            warehouse=self.warehouse,
            variant=self.variant,
            quantity=100
        )

    def test_stock_movement_quantity_must_be_positive(self):
        """Test that stock movement quantity must be positive."""
        with self.assertRaises(ValidationError):
            movement = StockMovement(
                movement_type=StockMovement.TYPE_SALE,
                variant=self.variant,
                to_warehouse=self.warehouse,
                quantity=-1,
                created_by=self.manager
            )
            movement.full_clean()
        
        with self.assertRaises(ValidationError):
            movement = StockMovement(
                movement_type=StockMovement.TYPE_SALE,
                variant=self.variant,
                to_warehouse=self.warehouse,
                quantity=0,
                created_by=self.manager
            )
            movement.full_clean()

    def test_stock_quantity_must_be_non_negative(self):
        """Test that stock quantity must be non-negative."""
        with self.assertRaises(ValidationError):
            stock = Stock(
                warehouse=self.warehouse,
                variant=self.variant,
                quantity=-1
            )
            stock.full_clean()

