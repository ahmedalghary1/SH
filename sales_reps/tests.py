from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts.models import User
from customers.models import Customer
from finance.models import CashAccount, PaymentTransaction
from inventory.models import Stock, StockMovement, Warehouse
from orders.models import Order
from products.models import Product, ProductVariant

from .models import SalesRepCollection
from .services import (
    assign_stock_to_sales_rep,
    get_or_create_sales_rep_cash_account,
    handover_sales_rep_cash,
    record_sales_rep_collection,
    record_sales_rep_sale,
    return_stock_from_sales_rep,
)


class SalesRepServiceTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username='manager', password='pass', role=User.ROLE_MANAGER)
        self.warehouse_user = User.objects.create_user(username='warehouse', password='pass', role=User.ROLE_WAREHOUSE)
        self.sales_rep = User.objects.create_user(username='rep', password='pass', role=User.ROLE_SALES)
        self.customer = Customer.objects.create(name='Sales Rep Customer', customer_type=Customer.TYPE_B2C, phone='01000000044', created_by=self.manager)
        self.warehouse = Warehouse.objects.create(name='Main Warehouse', warehouse_type=Warehouse.TYPE_MAIN)
        product = Product.objects.create(
            name='Field Shirt',
            sku='REP-001',
            retail_price=Decimal('300.00'),
            wholesale_price=Decimal('220.00'),
        )
        self.variant = ProductVariant.objects.create(product=product, variant_sku='REP-001-BLK-M', cost_price=Decimal('120.00'))
        self.stock = Stock.objects.create(warehouse=self.warehouse, variant=self.variant, quantity=10, min_quantity=1)
        self.cash = CashAccount.objects.create(name='Main Cash', balance=Decimal('1000.00'))
        self.order = Order.objects.create(
            order_number='ORD-REP-001',
            order_type=Order.TYPE_B2C,
            customer=self.customer,
            warehouse=self.warehouse,
            status=Order.STATUS_COMPLETED,
            total=Decimal('900.00'),
            paid_amount=Decimal('300.00'),
            remaining_amount=Decimal('600.00'),
            payment_status=Order.PAYMENT_PARTIAL,
            created_by=self.manager,
        )

    def _assignment(self, quantity=5):
        return assign_stock_to_sales_rep(
            sales_rep=self.sales_rep,
            product_variant=self.variant,
            source_warehouse=self.warehouse,
            quantity=quantity,
            assigned_by=self.warehouse_user,
        )

    def test_assign_stock_reduces_warehouse_stock_and_records_movement(self):
        assignment = self._assignment(quantity=4)
        self.stock.refresh_from_db()

        self.assertEqual(self.stock.quantity, 6)
        self.assertEqual(assignment.quantity_assigned, 4)
        self.assertEqual(assignment.quantity_remaining, 4)
        self.assertTrue(StockMovement.objects.filter(movement_type=StockMovement.TYPE_SALES_REP_ASSIGNMENT, quantity=4).exists())

    def test_assign_stock_rejects_unavailable_quantity(self):
        with self.assertRaises(ValidationError):
            self._assignment(quantity=11)

        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 10)

    def test_return_stock_increases_warehouse_stock_and_validates_remaining(self):
        assignment = self._assignment(quantity=5)

        return_stock_from_sales_rep(assignment=assignment, quantity=2, user=self.warehouse_user)
        assignment.refresh_from_db()
        self.stock.refresh_from_db()

        self.assertEqual(self.stock.quantity, 7)
        self.assertEqual(assignment.quantity_returned, 2)
        self.assertEqual(assignment.quantity_remaining, 3)
        self.assertTrue(StockMovement.objects.filter(movement_type=StockMovement.TYPE_SALES_REP_RETURN, quantity=2).exists())

        with self.assertRaises(ValidationError):
            return_stock_from_sales_rep(assignment=assignment, quantity=4, user=self.warehouse_user)

    def test_record_sale_reduces_assignment_without_touching_warehouse_stock(self):
        assignment = self._assignment(quantity=5)
        self.stock.refresh_from_db()
        stock_after_assignment = self.stock.quantity

        record_sales_rep_sale(assignment=assignment, quantity=3, user=self.warehouse_user)
        assignment.refresh_from_db()
        self.stock.refresh_from_db()

        self.assertEqual(self.stock.quantity, stock_after_assignment)
        self.assertEqual(assignment.quantity_sold, 3)
        self.assertEqual(assignment.quantity_remaining, 2)
        self.assertTrue(StockMovement.objects.filter(movement_type=StockMovement.TYPE_SALES_REP_SALE, quantity=3).exists())

    def test_record_collection_creates_transaction_and_updates_order_payment(self):
        collection = record_sales_rep_collection(
            sales_rep=self.sales_rep,
            customer=self.customer,
            order=self.order,
            amount=Decimal('250.00'),
            user=self.manager,
        )
        self.order.refresh_from_db()
        rep_cash = collection.cash_account
        rep_cash.refresh_from_db()

        self.assertEqual(collection.amount, Decimal('250.00'))
        self.assertEqual(self.order.paid_amount, Decimal('550.00'))
        self.assertEqual(self.order.remaining_amount, Decimal('350.00'))
        self.assertEqual(self.order.payment_status, Order.PAYMENT_PARTIAL)
        self.assertEqual(rep_cash.balance, Decimal('250.00'))
        self.assertTrue(PaymentTransaction.objects.filter(transaction_type=PaymentTransaction.TYPE_SALES_REP_COLLECTION, related_order=self.order).exists())

    def test_handover_creates_out_and_in_transactions_and_marks_collections(self):
        rep_cash = get_or_create_sales_rep_cash_account(self.sales_rep)
        record_sales_rep_collection(sales_rep=self.sales_rep, customer=self.customer, amount=Decimal('200.00'), cash_account=rep_cash, user=self.manager)
        record_sales_rep_collection(sales_rep=self.sales_rep, customer=self.customer, amount=Decimal('150.00'), cash_account=rep_cash, user=self.manager)

        handover_sales_rep_cash(
            sales_rep=self.sales_rep,
            amount=Decimal('350.00'),
            source_cash_account=rep_cash,
            target_cash_account=self.cash,
            user=self.manager,
        )
        rep_cash.refresh_from_db()
        self.cash.refresh_from_db()

        self.assertEqual(rep_cash.balance, Decimal('0.00'))
        self.assertEqual(self.cash.balance, Decimal('1350.00'))
        self.assertEqual(SalesRepCollection.objects.filter(sales_rep=self.sales_rep, handed_over=True).count(), 2)
        self.assertEqual(PaymentTransaction.objects.filter(transaction_type=PaymentTransaction.TYPE_SALES_REP_HANDOVER).count(), 2)

    def test_handover_rejects_amount_greater_than_unhanded_collections(self):
        rep_cash = get_or_create_sales_rep_cash_account(self.sales_rep)
        record_sales_rep_collection(sales_rep=self.sales_rep, customer=self.customer, amount=Decimal('100.00'), cash_account=rep_cash, user=self.manager)

        with self.assertRaises(ValidationError):
            handover_sales_rep_cash(
                sales_rep=self.sales_rep,
                amount=Decimal('101.00'),
                source_cash_account=rep_cash,
                target_cash_account=self.cash,
                user=self.manager,
            )

        rep_cash.refresh_from_db()
        self.cash.refresh_from_db()
        self.assertEqual(rep_cash.balance, Decimal('100.00'))
        self.assertEqual(self.cash.balance, Decimal('1000.00'))
