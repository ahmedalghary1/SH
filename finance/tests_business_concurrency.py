from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase

from accounts.models import User
from customers.models import Customer
from finance.models import CashAccount, PaymentTransaction
from finance.services import transfer_between_accounts
from inventory.models import Stock, Warehouse
from inventory.services import stock_in
from orders.models import Order
from orders.services import create_order
from products.models import Product, ProductVariant


@skipUnless(connection.vendor == 'postgresql', 'Row-lock concurrency requires PostgreSQL')
class BusinessConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username='parallel-manager', role='manager')

    def run_parallel(self, actions):
        start = Barrier(len(actions))
        def run(action):
            close_old_connections()
            try:
                start.wait(timeout=10)
                return action()
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=len(actions)) as pool:
            return [future.result(timeout=20) for future in [pool.submit(run, action) for action in actions]]

    def test_opposite_cash_transfers_do_not_deadlock_or_create_money(self):
        first = CashAccount.objects.create(name='Parallel A', balance=100)
        second = CashAccount.objects.create(name='Parallel B', balance=100)
        def transfer(source, target):
            transfer_between_accounts(from_account=CashAccount.objects.get(pk=source),
                to_account=CashAccount.objects.get(pk=target), amount=10,
                user=User.objects.get(pk=self.manager.pk))
        self.run_parallel([lambda: transfer(first.pk, second.pk), lambda: transfer(second.pk, first.pk)])
        self.assertEqual(list(CashAccount.objects.order_by('pk').values_list('balance', flat=True)), [100, 100])
        self.assertEqual(PaymentTransaction.objects.count(), 4)

    def test_two_concurrent_sales_cannot_oversell_the_same_stock(self):
        warehouse = Warehouse.objects.create(name='Parallel stock')
        customer = Customer.objects.create(name='Parallel customer')
        product = Product.objects.create(name='Parallel product', sku='PARALLEL')
        variant = ProductVariant.objects.create(product=product, variant_sku='PARALLEL-V', cost_price=1)
        stock_in(variant=variant, warehouse=warehouse, quantity=5, user=self.manager, unit_cost=1)
        def sell():
            try:
                create_order(order_data={'customer': Customer.objects.get(pk=customer.pk),
                    'warehouse': Warehouse.objects.get(pk=warehouse.pk), 'order_type': 'b2c', 'payment_method': 'credit'},
                    items=[{'variant': ProductVariant.objects.get(pk=variant.pk), 'quantity': 4, 'unit_price': 10}],
                    user=User.objects.get(pk=self.manager.pk), confirm=True)
                return 'sold'
            except ValidationError:
                return 'rejected'
        self.assertCountEqual(self.run_parallel([sell, sell]), ['sold', 'rejected'])
        self.assertEqual(Stock.objects.get(warehouse=warehouse, variant=variant).quantity, 1)
        self.assertEqual(Order.objects.count(), 1)
