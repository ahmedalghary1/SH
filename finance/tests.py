from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from customers.models import Customer
from inventory.models import Warehouse
from orders.models import Order
from purchases.models import Supplier

from .models import CashAccount, PaymentTransaction
from .services import (
    add_expense,
    collect_order_payment,
    record_customer_payment,
    record_order_sale_payment,
    transfer_between_accounts,
)


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

    def test_record_order_sale_payment_accepts_nullable_customer(self):
        order = Order.objects.create(
            order_number='ORD-FIN-NO-CUSTOMER',
            order_type=Order.TYPE_B2C,
            customer=None,
            warehouse=self.warehouse,
            total=Decimal('250.00'),
            created_by=self.user,
        )

        tx = record_order_sale_payment(order=order, cash_account=self.cash, user=self.user)
        order.refresh_from_db()
        self.cash.refresh_from_db()

        self.assertIsNotNone(tx)
        self.assertIsNone(tx.related_customer)
        self.assertEqual(order.paid_amount, Decimal('250.00'))
        self.assertEqual(order.remaining_amount, Decimal('0'))
        self.assertEqual(order.payment_status, Order.PAYMENT_PAID)
        self.assertEqual(self.cash.balance, Decimal('1250.00'))

    def test_transfer_between_accounts_moves_balance(self):
        transfer_between_accounts(from_account=self.cash, to_account=self.bank, amount=Decimal('300.00'), user=self.user)
        self.cash.refresh_from_db()
        self.bank.refresh_from_db()

        self.assertEqual(self.cash.balance, Decimal('700.00'))
        self.assertEqual(self.bank.balance, Decimal('300.00'))
        self.assertEqual(PaymentTransaction.objects.filter(transaction_type=PaymentTransaction.TYPE_TRANSFER).count(), 2)

    def test_supplier_payment_view_uses_finance_service_and_decreases_cash(self):
        self.client.force_login(self.user)
        supplier = Supplier.objects.create(name='Finance Supplier', current_balance=Decimal('600.00'))

        response = self.client.post(reverse('finance:supplier_payment_create'), {
            'supplier': supplier.pk,
            'cash_account': self.cash.pk,
            'amount': '250.00',
            'transaction_date': '2026-06-12',
            'notes': 'supplier payment',
        })

        self.assertRedirects(response, reverse('finance:cash'))
        self.cash.refresh_from_db()
        supplier.refresh_from_db()
        self.assertEqual(self.cash.balance, Decimal('750.00'))
        self.assertEqual(supplier.current_balance, Decimal('350.00'))
        self.assertTrue(PaymentTransaction.objects.filter(
            transaction_type=PaymentTransaction.TYPE_SUPPLIER_PAYMENT,
            direction=PaymentTransaction.DIRECTION_OUT,
            amount=Decimal('250.00'),
            related_supplier=supplier,
        ).exists())

    def test_transaction_delete_reverses_cash_balance_for_incoming_transaction(self):
        self.client.force_login(self.user)
        tx = record_customer_payment(
            order=None,
            customer=self.customer,
            amount=Decimal('200.00'),
            cash_account=self.cash,
            user=self.user,
        )
        self.cash.refresh_from_db()
        self.assertEqual(self.cash.balance, Decimal('1200.00'))

        response = self.client.post(reverse('finance:transaction_delete', kwargs={'pk': tx.pk}))

        self.assertRedirects(response, reverse('finance:transactions'))
        self.cash.refresh_from_db()
        self.assertEqual(self.cash.balance, Decimal('1000.00'))
        self.assertFalse(PaymentTransaction.objects.filter(pk=tx.pk).exists())

    def test_transaction_delete_reverses_cash_balance_for_outgoing_transaction(self):
        self.client.force_login(self.user)
        tx = add_expense(amount=Decimal('150.00'), cash_account=self.cash, user=self.user, notes='Office rent')
        self.cash.refresh_from_db()
        self.assertEqual(self.cash.balance, Decimal('850.00'))

        response = self.client.post(reverse('finance:transaction_delete', kwargs={'pk': tx.pk}))

        self.assertRedirects(response, reverse('finance:transactions'))
        self.cash.refresh_from_db()
        self.assertEqual(self.cash.balance, Decimal('1000.00'))
        self.assertFalse(PaymentTransaction.objects.filter(pk=tx.pk).exists())

    def test_cash_account_detail_shows_incoming_and_outgoing_transactions(self):
        self.client.force_login(self.user)
        collect_order_payment(order=self.order, amount=Decimal('200.00'), cash_account=self.cash, user=self.user)
        add_expense(amount=Decimal('150.00'), cash_account=self.cash, user=self.user, notes='Office rent')

        response = self.client.get(reverse('finance:account_detail', kwargs={'pk': self.cash.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'الحركات المالية الداخلة والخارجة')
        self.assertContains(response, 'تحصيل من عميل')
        self.assertContains(response, 'مصروف')
        self.assertContains(response, 'إجمالي الداخل')
        self.assertContains(response, 'إجمالي الخارج')
        self.assertNotContains(response, reverse('finance:collection_create'))

    def test_cash_account_detail_filters_transactions_by_direction(self):
        self.client.force_login(self.user)
        collect_order_payment(order=self.order, amount=Decimal('200.00'), cash_account=self.cash, user=self.user)
        add_expense(amount=Decimal('150.00'), cash_account=self.cash, user=self.user, notes='Office rent')

        response = self.client.get(reverse('finance:account_detail', kwargs={'pk': self.cash.pk}), data={
            'direction': PaymentTransaction.DIRECTION_OUT,
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'مصروف')
        self.assertNotContains(response, self.order.order_number)
        self.assertTrue(all(tx.direction == PaymentTransaction.DIRECTION_OUT for tx in response.context['transactions']))
