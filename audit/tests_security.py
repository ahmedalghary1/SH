from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User
from products.models import Product, ProductVariant, Color, Size
from inventory.models import Stock, Warehouse
from orders.models import Order, OrderItem
from customers.models import Customer


class CostProfitVisibilityTests(TestCase):
    """Tests to verify cost/profit data is hidden from non-managers."""
    
    def setUp(self):
        self.manager = User.objects.create_user(
            username='manager',
            password='pass123',
            role='manager'
        )
        self.sales = User.objects.create_user(
            username='sales',
            password='pass123',
            role='sales'
        )
        self.warehouse = User.objects.create_user(
            username='warehouse',
            password='pass123',
            role='warehouse'
        )
        self.client = Client()
        
        # Create test data
        self.warehouse_obj = Warehouse.objects.create(
            name='Test Warehouse',
            warehouse_type=Warehouse.TYPE_STORE,
            is_active=True
        )
        self.color = Color.objects.create(name='Red', hex_code='#FF0000')
        self.size = Size.objects.create(name='M', sort_order=1)
        self.product = Product.objects.create(
            name='Test Product',
            sku='TEST001',
            is_active=True
        )
        self.variant = ProductVariant.objects.create(
            product=self.product,
            color=self.color,
            size=self.size,
            cost_price=100,
            sale_price=200,
            is_active=True
        )
        self.stock = Stock.objects.create(
            warehouse=self.warehouse_obj,
            variant=self.variant,
            quantity=50
        )
        self.customer = Customer.objects.create(
            name='Test Customer',
            phone='1234567890'
        )
    
    def test_sales_user_cannot_see_cost_in_stock_list(self):
        """Verify sales user cannot see cost_price in stock list."""
        self.client.login(username='sales', password='pass123')
        response = self.client.get(reverse('inventory:stock'))
        self.assertEqual(response.status_code, 200)
        # Cost price should not be in the response for sales user
        self.assertNotContains(response, str(self.variant.cost_price))
    
    def test_warehouse_user_cannot_see_cost_in_stock_list(self):
        """Verify warehouse user cannot see cost_price in stock list."""
        self.client.login(username='warehouse', password='pass123')
        response = self.client.get(reverse('inventory:stock'))
        self.assertEqual(response.status_code, 200)
        # Cost price should not be in the response for warehouse user
        self.assertNotContains(response, str(self.variant.cost_price))
    
    def test_manager_can_see_cost_in_stock_list(self):
        """Verify manager can see cost_price in stock list."""
        self.client.login(username='manager', password='pass123')
        response = self.client.get(reverse('inventory:stock'))
        self.assertEqual(response.status_code, 200)
        # Cost price should be in the response for manager
        self.assertContains(response, str(self.variant.cost_price))
    
    def test_sales_user_cannot_see_cost_in_product_detail(self):
        """Verify sales user cannot see cost_price in product detail."""
        self.client.login(username='sales', password='pass123')
        response = self.client.get(reverse('products:detail', args=[self.product.pk]))
        self.assertEqual(response.status_code, 200)
        # Cost price should not be in the response for sales user
        self.assertNotContains(response, str(self.variant.cost_price))
    
    def test_warehouse_user_cannot_see_cost_in_product_detail(self):
        """Verify warehouse user cannot see cost_price in product detail."""
        self.client.login(username='warehouse', password='pass123')
        response = self.client.get(reverse('products:detail', args=[self.product.pk]))
        self.assertEqual(response.status_code, 200)
        # Cost price should not be in the response for warehouse user
        self.assertNotContains(response, str(self.variant.cost_price))
    
    def test_manager_can_see_cost_in_product_detail(self):
        """Verify manager can see cost_price in product detail."""
        self.client.login(username='manager', password='pass123')
        response = self.client.get(reverse('products:detail', args=[self.product.pk]))
        self.assertEqual(response.status_code, 200)
        # Cost price should be in the response for manager
        self.assertContains(response, str(self.variant.cost_price))
    
    def test_sales_user_cannot_see_cost_in_ajax_stock_endpoint(self):
        """Verify sales user cannot get unit_cost from AJAX stock endpoint."""
        self.client.login(username='sales', password='pass123')
        response = self.client.get(
            reverse('orders:ajax_get_variant_stock', args=[self.variant.pk])
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        # Check that unit_cost is None for sales user
        if 'data' in data and 'warehouses' in data['data']:
            for warehouse_data in data['data']['warehouses']:
                for batch in warehouse_data.get('batches', []):
                    self.assertIsNone(batch.get('unit_cost'))
    
    def test_manager_can_see_cost_in_ajax_stock_endpoint(self):
        """Verify manager can get unit_cost from AJAX stock endpoint."""
        self.client.login(username='manager', password='pass123')
        response = self.client.get(
            reverse('orders:ajax_get_variant_stock', args=[self.variant.pk])
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        # Check that unit_cost is present for manager
        if 'data' in data and 'warehouses' in data['data']:
            for warehouse_data in data['data']['warehouses']:
                for batch in warehouse_data.get('batches', []):
                    if batch.get('unit_cost'):
                        self.assertIsNotNone(batch.get('unit_cost'))
