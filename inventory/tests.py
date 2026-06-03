from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from products.models import Product, ProductVariant

from .models import Stock, Warehouse


class StockListViewTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(
            username='manager',
            password='pass12345',
            role=User.ROLE_MANAGER,
        )
        self.product = Product.objects.create(
            name='Cotton Shirt',
            sku='SH-001',
            retail_price=250,
            wholesale_price=180,
        )
        self.variant = ProductVariant.objects.create(
            product=self.product,
            variant_sku='SH-001-BLK-M',
            barcode='123456789',
        )
        self.main_warehouse = Warehouse.objects.create(
            name='Main Warehouse',
            warehouse_type=Warehouse.TYPE_MAIN,
        )
        self.branch_warehouse = Warehouse.objects.create(
            name='Branch Warehouse',
            warehouse_type=Warehouse.TYPE_STORE,
        )
        Stock.objects.create(
            warehouse=self.main_warehouse,
            variant=self.variant,
            quantity=12,
            min_quantity=3,
        )
        Stock.objects.create(
            warehouse=self.branch_warehouse,
            variant=self.variant,
            quantity=5,
            min_quantity=2,
        )

    def test_can_filter_stock_by_warehouse(self):
        self.client.login(username='manager', password='pass12345')

        response = self.client.get(
            reverse('inventory:stock'),
            {'warehouse': self.main_warehouse.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Main Warehouse')
        self.assertContains(response, 'SH-001')
        self.assertContains(response, 'SH-001-BLK-M')
        self.assertContains(response, '>12<', html=False)
        self.assertQuerySetEqual(
            response.context['stocks'],
            [Stock.objects.get(warehouse=self.main_warehouse, variant=self.variant)],
        )
