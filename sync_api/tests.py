from decimal import Decimal

from django.test import TestCase

from accounts.models import User
from customers.models import Customer
from finance.models import CashAccount, PaymentTransaction
from inventory.models import Stock, Warehouse
from orders.models import Order
from orders.services import create_order
from products.models import Product, ProductVariant

from .services import process_order


class OfflineOrderSafetyTests(TestCase):
    def test_offline_delete_uses_business_cancellation_and_reverses_effects(self):
        user = User.objects.create_user(username='sync-manager', role=User.ROLE_MANAGER)
        customer = Customer.objects.create(name='Sync Customer', created_by=user)
        warehouse = Warehouse.objects.create(name='Sync Warehouse', warehouse_type=Warehouse.TYPE_MAIN)
        product = Product.objects.create(
            name='Sync Product', sku='SYNC-1', retail_price=Decimal('100.00'),
        )
        variant = ProductVariant.objects.create(
            product=product, variant_sku='SYNC-1-A', cost_price=Decimal('40.00'),
        )
        stock = Stock.objects.create(warehouse=warehouse, variant=variant, quantity=3)
        cash = CashAccount.get_default()
        order = create_order(
            order_data={
                'customer': customer,
                'warehouse': warehouse,
                'order_type': Order.TYPE_B2C,
                'payment_method': Order.METHOD_CASH,
            },
            items=[{
                'variant': variant,
                'warehouse': warehouse,
                'quantity': 1,
                'unit_price': Decimal('100.00'),
            }],
            user=user,
            confirm=True,
        )
        stock.refresh_from_db()
        cash.refresh_from_db()
        self.assertEqual(stock.quantity, 2)
        self.assertEqual(cash.balance, Decimal('100.00'))

        process_order({
            'operation_type': 'delete',
            'local_uuid': 'offline-delete-1',
            'device_id': 'device-1',
            'payload': {'order': {'server_id': order.pk}},
        }, user)

        order.refresh_from_db()
        stock.refresh_from_db()
        cash.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_CANCELLED)
        self.assertEqual(stock.quantity, 3)
        self.assertEqual(cash.balance, Decimal('0.00'))
        self.assertTrue(PaymentTransaction.objects.filter(
            related_order=order,
            transaction_type=PaymentTransaction.TYPE_REFUND,
            direction=PaymentTransaction.DIRECTION_OUT,
        ).exists())
