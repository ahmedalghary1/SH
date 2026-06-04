from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from customers.models import Customer
from finance.models import CashAccount, PaymentTransaction
from inventory.models import Stock, Warehouse
from orders.models import Order, OrderItem
from products.models import Product, ProductVariant
from sales_reps.models import SalesRepStockAssignment


class ReportPermissionTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username='manager', password='pass', role=User.ROLE_MANAGER)
        self.sales = User.objects.create_user(username='sales', password='pass', role=User.ROLE_SALES)
        self.other_sales = User.objects.create_user(username='other-sales', password='pass', role=User.ROLE_SALES)
        self.warehouse_user = User.objects.create_user(username='warehouse', password='pass', role=User.ROLE_WAREHOUSE)
        self.customer = Customer.objects.create(name='Customer A', phone='01000000001', created_by=self.sales)
        self.warehouse = Warehouse.objects.create(name='Main', warehouse_type=Warehouse.TYPE_MAIN)
        product = Product.objects.create(
            name='Shirt',
            sku='SH-001',
            retail_price=Decimal('300.00'),
            wholesale_price=Decimal('220.00'),
        )
        self.variant = ProductVariant.objects.create(product=product, variant_sku='SH-001-BLK-M', cost_price=Decimal('120.00'))
        Stock.objects.create(warehouse=self.warehouse, variant=self.variant, quantity=2, min_quantity=5)
        self.order = Order.objects.create(
            order_number='ORD-RPT-001',
            order_type=Order.TYPE_B2C,
            customer=self.customer,
            warehouse=self.warehouse,
            subtotal=Decimal('600.00'),
            discount=Decimal('20.00'),
            total=Decimal('580.00'),
            total_cost=Decimal('240.00'),
            gross_profit=Decimal('340.00'),
            paid_amount=Decimal('300.00'),
            remaining_amount=Decimal('280.00'),
            created_by=self.sales,
        )
        OrderItem.objects.create(
            order=self.order,
            variant=self.variant,
            quantity=2,
            unit_price=Decimal('300.00'),
            total=Decimal('580.00'),
            unit_cost=Decimal('120.00'),
            cost_total=Decimal('240.00'),
            profit_total=Decimal('340.00'),
        )
        CashAccount.objects.create(name='Main cash', balance=Decimal('500.00'))
        PaymentTransaction.objects.create(
            transaction_type=PaymentTransaction.TYPE_EXPENSE,
            direction=PaymentTransaction.DIRECTION_OUT,
            amount=Decimal('50.00'),
            cash_account=CashAccount.objects.get(name='Main cash'),
            created_by=self.manager,
        )
        SalesRepStockAssignment.objects.create(
            sales_rep=self.sales,
            product_variant=self.variant,
            source_warehouse=self.warehouse,
            quantity_assigned=10,
            quantity_sold=3,
            quantity_returned=1,
            quantity_remaining=6,
            assigned_by=self.warehouse_user,
        )
        SalesRepStockAssignment.objects.create(
            sales_rep=self.other_sales,
            product_variant=self.variant,
            source_warehouse=self.warehouse,
            quantity_assigned=5,
            quantity_remaining=5,
            assigned_by=self.warehouse_user,
        )

    def test_manager_can_open_profitability_report(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse('reports:profitability'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'gross_profit')
        self.assertContains(response, '340')

    def test_sales_user_cannot_open_profitability_report(self):
        self.client.force_login(self.sales)
        response = self.client.get(reverse('reports:profitability'))

        self.assertEqual(response.status_code, 403)

    def test_sales_report_omits_cost_and_profit_for_sales_user(self):
        self.client.force_login(self.sales)
        response = self.client.get(reverse('reports:sales'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ORD-RPT-001')
        self.assertNotContains(response, 'gross_profit')
        self.assertNotContains(response, 'total_cost')
        self.assertNotContains(response, 'profit_total')

    def test_sales_user_cannot_export_profitability(self):
        self.client.force_login(self.sales)
        response = self.client.get(reverse('reports:profitability_export'))

        self.assertEqual(response.status_code, 403)

    def test_sales_rep_custody_is_filtered_to_logged_in_rep(self):
        self.client.force_login(self.sales)
        response = self.client.get(reverse('reports:sales_rep_custody'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'sales')
        self.assertNotContains(response, 'other-sales')

    def test_warehouse_can_open_low_stock_without_financial_data(self):
        self.client.force_login(self.warehouse_user)
        response = self.client.get(reverse('reports:low_stock'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Low stock report')
        self.assertNotContains(response, 'gross_profit')
