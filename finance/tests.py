from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts.models import User
from customers.models import Customer
from inventory.models import Warehouse
from orders.models import Order

from .models import CashAccount, PaymentTransaction
from .services import add_expense, collect_order_payment, transfer_between_accounts


class FinanceServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='manager', password='pass', role=User.ROLE_MANAGER)
        self.customer = Customer.objects.create(name='Test Customer', customer_type='b2c', phone='01000000001', created_by=self.user)
        self.warehouse = Warehouse.objects.create(name='Main', warehouse_type=Warehouse.TYPE_MAIN)
        self.cash = CashAccount.objects.create(name='Main Cash', balance=Decimal('1000.00'))
        self.bank = CashAccount.objects.create(name='Bank', account_type=CashAccount.TYPE_BANK, balance=Decimal('0.00'))
        self.order = Order.objects.create(
            order_number='ORD-FIN-001',
            order_type=Order.TYPE_B2C,
            customer=self.customer,
            warehouse=self.warehouse,
            total=Decimal('500.00'),
            paid_amount=Decimal('100.00'),
            remaining_amount=Decimal('400.00'),
            created_by=self.user,
        )

    def test_expense_decreases_cash_account_balance(self):
        add_expense(amount=Decimal('150.00'), cash_account=self.cash, user=self.user, notes='Office rent')
        self.cash.refresh_from_db()

        self.assertEqual(self.cash.balance, Decimal('850.00'))
        self.assertTrue(PaymentTransaction.objects.filter(transaction_type=PaymentTransaction.TYPE_EXPENSE).exists())

    def test_expense_rejects_insufficient_balance(self):
        with self.assertRaises(ValidationError):
            add_expense(amount=Decimal('1500.00'), cash_account=self.cash, user=self.user)

        self.cash.refresh_from_db()
        self.assertEqual(self.cash.balance, Decimal('1000.00'))

    def test_collect_order_payment_updates_order_and_cash(self):
        collect_order_payment(order=self.order, amount=Decimal('200.00'), cash_account=self.cash, user=self.user)
        self.order.refresh_from_db()
        self.cash.refresh_from_db()

        self.assertEqual(self.order.paid_amount, Decimal('300.00'))
        self.assertEqual(self.order.remaining_amount, Decimal('200.00'))
        self.assertEqual(self.cash.balance, Decimal('1200.00'))

    def test_transfer_between_accounts_moves_balance(self):
        transfer_between_accounts(from_account=self.cash, to_account=self.bank, amount=Decimal('300.00'), user=self.user)
        self.cash.refresh_from_db()
        self.bank.refresh_from_db()

        self.assertEqual(self.cash.balance, Decimal('700.00'))
        self.assertEqual(self.bank.balance, Decimal('300.00'))
        self.assertEqual(PaymentTransaction.objects.filter(transaction_type=PaymentTransaction.TYPE_TRANSFER).count(), 2)
