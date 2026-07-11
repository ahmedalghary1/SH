from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts.models import User
from products.models import Category, Color, Product, ProductVariant, Size
from purchases.models import PurchaseOrder, Supplier
from purchases.services import create_purchase_order


class PurchaseDiscountTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='discount-manager', password='x', role=User.ROLE_MANAGER)
        self.supplier = Supplier.objects.create(name='Supplier')
        category = Category.objects.create(name='Category')
        product = Product.objects.create(name='Product', sku='DISC-1', category=category)
        self.variant = ProductVariant.objects.create(product=product, color=Color.objects.create(name='Black'), size=Size.objects.create(name='M'), variant_sku='DISC-1-M')

    def create(self, discount_type, value):
        return create_purchase_order(supplier=self.supplier, user=self.user, items=[{'product_variant': self.variant, 'quantity': 2, 'unit_cost': Decimal('100')}], discount_type=discount_type, discount_value=value)

    def test_fixed_and_percent_discounts_are_calculated_in_backend(self):
        fixed = self.create(PurchaseOrder.DISCOUNT_FIXED, Decimal('25'))
        percent = self.create(PurchaseOrder.DISCOUNT_PERCENT, Decimal('10'))
        self.assertEqual(fixed.total_amount, Decimal('175.00'))
        self.assertEqual(percent.total_amount, Decimal('180.00'))

    def test_invalid_discount_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.create(PurchaseOrder.DISCOUNT_PERCENT, Decimal('101'))
