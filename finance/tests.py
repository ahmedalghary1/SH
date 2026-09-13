from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from customers.models import Customer
from inventory.models import Warehouse
from orders.models import Order
from purchases.models import Supplier

from .forms import CustomerCollectionForm, ExpenseForm
from .models import CashAccount, PaymentTransaction
from .services import (
    add_expense,
    build_customer_statement,
    collect_order_payment,
    collect_customer_balance_payment,
    record_customer_payment,
    record_customer_refund_payment,
    record_order_sale_payment,
    transfer_between_accounts,
    replace_expense,
)


class FinanceServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='manager', password='pass', role=User.ROLE_MANAGER)
        self.customer = Customer.objects.create(
            name='Test Customer',
            customer_type='b2c',
            phone='01000000001',
            opening_balance=Decimal('200.00'),
            created_by=self.user,
        )
        self.warehouse = Warehouse.objects.create(name='Main', warehouse_type=Warehouse.TYPE_MAIN)
        self.cash = CashAccount.objects.create(name='Main Cash', balance=Decimal('1000.00'))
        self.bank = CashAccount.objects.create(name='Bank', account_type=CashAccount.TYPE_BANK, balance=Decimal('0.00'))
        self.order = Order.objects.create(
            order_number='ORD-FIN-001',
            order_type=Order.TYPE_B2C,
            customer=self.customer,
            warehouse=self.warehouse,
            status=Order.STATUS_CONFIRMED,
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

    def test_receipt_and_expense_list_totals_follow_type_filter(self):
        PaymentTransaction.objects.create(
            transaction_type=PaymentTransaction.TYPE_CUSTOMER_PAYMENT,
            direction=PaymentTransaction.DIRECTION_IN,
            amount=Decimal('225.00'),
            cash_account=self.cash,
            related_customer=self.customer,
            created_by=self.user,
        )
        PaymentTransaction.objects.create(
            transaction_type=PaymentTransaction.TYPE_EXPENSE,
            direction=PaymentTransaction.DIRECTION_OUT,
            amount=Decimal('80.00'),
            cash_account=self.cash,
            created_by=self.user,
        )
        self.client.force_login(self.user)

        receipt_response = self.client.get(
            reverse('finance:transactions'),
            {'type': PaymentTransaction.TYPE_CUSTOMER_PAYMENT},
        )
        expense_response = self.client.get(
            reverse('finance:transactions'),
            {'type': PaymentTransaction.TYPE_EXPENSE},
        )

        self.assertEqual(receipt_response.context['transaction_totals']['transaction_count'], 1)
        self.assertEqual(receipt_response.context['transaction_totals']['total_amount'], Decimal('225.00'))
        self.assertEqual(receipt_response.context['transaction_totals']['total_in'], Decimal('225.00'))
        self.assertEqual(receipt_response.context['transaction_totals']['total_out'], Decimal('0.00'))
        self.assertEqual(expense_response.context['transaction_totals']['transaction_count'], 1)
        self.assertEqual(expense_response.context['transaction_totals']['total_amount'], Decimal('80.00'))
        self.assertEqual(expense_response.context['transaction_totals']['net_amount'], Decimal('-80.00'))
        self.assertContains(receipt_response, 'sticky-table-wrap')
        self.assertContains(expense_response, 'الإجمالي (1 حركة)')

    def test_expense_rejects_insufficient_balance(self):
        with self.assertRaises(ValidationError):
            add_expense(amount=Decimal('1500.00'), cash_account=self.cash, user=self.user)

        self.cash.refresh_from_db()
        self.assertEqual(self.cash.balance, Decimal('1000.00'))

    def test_replace_expense_reverses_old_value_and_applies_new_value(self):
        expense = add_expense(amount=Decimal('150.00'), cash_account=self.cash, user=self.user)

        replacement = replace_expense(
            payment_transaction=expense,
            amount=Decimal('90.00'),
            cash_account=self.cash,
            user=self.user,
            notes='Corrected expense',
        )

        self.cash.refresh_from_db()
        self.assertEqual(self.cash.balance, Decimal('910.00'))
        self.assertFalse(PaymentTransaction.objects.filter(pk=expense.pk).exists())
        self.assertEqual(replacement.amount, Decimal('90.00'))

    def test_expense_form_requires_cash_account_to_deduct_from(self):
        form = ExpenseForm(data={
            'cash_account': self.cash.pk,
            'amount': '150.00',
            'transaction_date': '2026-06-12',
            'notes': 'Office rent',
        })

        self.assertTrue(form.is_valid(), form.errors.as_text())
        self.assertEqual(form.fields['cash_account'].label, 'الخزنة التي سيتم الخصم منها')

    def test_expense_create_view_deducts_from_selected_cash_account(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse('finance:expense_create'), {
            'cash_account': self.cash.pk,
            'amount': '150.00',
            'transaction_date': '2026-06-12T13:40',
            'notes': 'Office rent',
        })

        self.assertRedirects(response, reverse('finance:transactions'))
        self.cash.refresh_from_db()
        self.assertEqual(self.cash.balance, Decimal('850.00'))
        expense = PaymentTransaction.objects.get(
            transaction_type=PaymentTransaction.TYPE_EXPENSE,
            direction=PaymentTransaction.DIRECTION_OUT,
            amount=Decimal('150.00'),
            cash_account=self.cash,
        )
        self.assertEqual(str(expense.transaction_date), '2026-06-12')
        self.assertEqual(expense.transaction_time.strftime('%H:%M'), '13:40')

    def test_customer_collection_saves_selected_date_and_time(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse('finance:collection_create'), {
            'cash_account': self.cash.pk,
            'customer': self.customer.pk,
            'amount': '75.00',
            'transaction_date': '2026-06-13T09:25',
            'notes': 'dated receipt',
        })

        self.assertRedirects(response, reverse('finance:collection_create'))
        receipt = PaymentTransaction.objects.get(
            transaction_type=PaymentTransaction.TYPE_CUSTOMER_PAYMENT,
            direction=PaymentTransaction.DIRECTION_IN,
            amount=Decimal('75.00'),
            related_customer=self.customer,
        )
        self.assertEqual(str(receipt.transaction_date), '2026-06-13')
        self.assertEqual(receipt.transaction_time.strftime('%H:%M'), '09:25')

    def test_collect_order_payment_updates_order_and_cash(self):
        collect_order_payment(order=self.order, amount=Decimal('200.00'), cash_account=self.cash, user=self.user)
        self.order.refresh_from_db()
        self.cash.refresh_from_db()

        self.assertEqual(self.order.paid_amount, Decimal('300.00'))
        self.assertEqual(self.order.remaining_amount, Decimal('200.00'))
        self.assertEqual(self.cash.balance, Decimal('1200.00'))

    def test_credit_invoice_then_account_receipt_keeps_all_balances_in_sync(self):
        self.customer.opening_balance = Decimal('0.00')
        self.customer.save(update_fields=['opening_balance'])
        self.order.paid_amount = Decimal('0.00')
        self.order.remaining_amount = Decimal('500.00')
        self.order.payment_status = Order.PAYMENT_UNPAID
        self.order.save(update_fields=['paid_amount', 'remaining_amount', 'payment_status'])

        before = build_customer_statement(self.customer)
        self.assertEqual(before['current_balance'], Decimal('500.00'))

        collect_customer_balance_payment(
            customer=self.customer,
            amount=Decimal('125.00'),
            cash_account=self.cash,
            user=self.user,
        )

        self.order.refresh_from_db()
        self.customer.refresh_from_db()
        self.cash.refresh_from_db()
        after = build_customer_statement(self.customer)

        self.assertEqual(self.order.paid_amount, Decimal('125.00'))
        self.assertEqual(self.order.remaining_amount, Decimal('375.00'))
        self.assertEqual(after['current_balance'], Decimal('375.00'))
        self.assertEqual(self.customer.opening_balance, Decimal('0.00'))
        self.assertEqual(self.cash.balance, Decimal('1125.00'))
        self.assertTrue(PaymentTransaction.objects.filter(
            related_order=self.order,
            transaction_type=PaymentTransaction.TYPE_CUSTOMER_PAYMENT,
            amount=Decimal('125.00'),
        ).exists())

    def test_collect_customer_balance_payment_allocates_to_opening_balance_then_orders(self):
        second_order = Order.objects.create(
            order_number='ORD-FIN-002',
            order_type=Order.TYPE_B2C,
            customer=self.customer,
            warehouse=self.warehouse,
            status=Order.STATUS_CONFIRMED,
            total=Decimal('300.00'),
            paid_amount=Decimal('0.00'),
            remaining_amount=Decimal('300.00'),
            created_by=self.user,
        )

        collect_customer_balance_payment(
            customer=self.customer,
            amount=Decimal('500.00'),
            cash_account=self.cash,
            user=self.user,
        )
        self.customer.refresh_from_db()
        self.order.refresh_from_db()
        second_order.refresh_from_db()
        self.cash.refresh_from_db()

        self.assertEqual(self.customer.opening_balance, Decimal('200.00'))
        self.assertEqual(self.order.paid_amount, Decimal('400.00'))
        self.assertEqual(self.order.remaining_amount, Decimal('100.00'))
        self.assertEqual(second_order.remaining_amount, Decimal('300.00'))
        self.assertEqual(self.cash.balance, Decimal('1500.00'))

    def test_collect_customer_balance_payment_stores_overpayment_as_customer_credit(self):
        collect_customer_balance_payment(
            customer=self.customer,
            amount=Decimal('700.00'),
            cash_account=self.cash,
            user=self.user,
        )
        self.customer.refresh_from_db()
        self.order.refresh_from_db()
        self.cash.refresh_from_db()

        self.assertEqual(self.customer.opening_balance, Decimal('200.00'))
        self.assertEqual(build_customer_statement(self.customer)['current_balance'], Decimal('-100.00'))
        self.assertEqual(self.order.paid_amount, Decimal('500.00'))
        self.assertEqual(self.order.remaining_amount, Decimal('0.00'))
        self.assertEqual(self.cash.balance, Decimal('1700.00'))

    def test_customer_collection_form_accepts_negative_amount_without_order(self):
        form = CustomerCollectionForm(data={
            'cash_account': self.cash.pk,
            'customer': self.customer.pk,
            'amount': '-50.00',
            'transaction_date': '2026-06-12',
        })

        self.assertTrue(form.is_valid(), form.errors.as_text())
        self.assertEqual(form.fields['amount'].label, 'القبض')

    def test_customer_collection_form_shows_all_active_customers_for_sales_user(self):
        sales_user = User.objects.create_user(username='sales', password='pass', role=User.ROLE_SALES)
        other_sales = User.objects.create_user(username='sales-2', password='pass', role=User.ROLE_SALES)
        other_customer = Customer.objects.create(
            name='Other Customer',
            customer_type='b2c',
            phone='01000000002',
            sales_representative=other_sales,
            created_by=self.user,
        )

        form = CustomerCollectionForm(user=sales_user)
        customer_ids = list(form.fields['customer'].queryset.values_list('pk', flat=True))

        self.assertIn(self.customer.pk, customer_ids)
        self.assertIn(other_customer.pk, customer_ids)

    def test_customer_payment_edit_form_shows_all_active_customers_for_sales_user(self):
        sales_user = User.objects.create_user(username='sales-edit', password='pass', role=User.ROLE_SALES)
        other_sales = User.objects.create_user(username='sales-edit-2', password='pass', role=User.ROLE_SALES)
        other_customer = Customer.objects.create(
            name='Edit Customer',
            customer_type='b2c',
            phone='01000000003',
            sales_representative=other_sales,
            created_by=self.user,
        )

        from .forms import CustomerPaymentEditForm

        form = CustomerPaymentEditForm(user=sales_user)
        customer_ids = list(form.fields['customer'].queryset.values_list('pk', flat=True))

        self.assertIn(self.customer.pk, customer_ids)
        self.assertIn(other_customer.pk, customer_ids)

    def test_customer_collection_form_accepts_negative_amount_with_order(self):
        form = CustomerCollectionForm(data={
            'cash_account': self.cash.pk,
            'customer': self.customer.pk,
            'order': self.order.pk,
            'amount': '-50.00',
            'transaction_date': '2026-06-12',
        })

        self.assertTrue(form.is_valid(), form.errors.as_text())

    def test_negative_customer_collection_records_refund_and_updates_customer_balance(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse('finance:collection_create'), {
            'cash_account': self.cash.pk,
            'customer': self.customer.pk,
            'amount': '-50.00',
            'transaction_date': '2026-06-12',
        })

        self.assertRedirects(response, reverse('finance:collection_create'))
        self.cash.refresh_from_db()
        self.customer.refresh_from_db()
        self.assertEqual(self.cash.balance, Decimal('950.00'))
        self.assertEqual(self.customer.opening_balance, Decimal('200.00'))
        self.assertEqual(build_customer_statement(self.customer)['current_balance'], Decimal('650.00'))
        self.assertTrue(PaymentTransaction.objects.filter(
            transaction_type=PaymentTransaction.TYPE_REFUND,
            direction=PaymentTransaction.DIRECTION_OUT,
            amount=Decimal('50.00'),
            related_customer=self.customer,
            related_order__isnull=True,
        ).exists())

    def test_collect_order_payment_accepts_negative_amount_and_reopens_balance(self):
        collect_order_payment(order=self.order, amount=Decimal('-50.00'), cash_account=self.cash, user=self.user)
        self.order.refresh_from_db()
        self.cash.refresh_from_db()

        self.assertEqual(self.order.paid_amount, Decimal('50.00'))
        self.assertEqual(self.order.remaining_amount, Decimal('450.00'))
        self.assertEqual(self.cash.balance, Decimal('950.00'))
        self.assertTrue(PaymentTransaction.objects.filter(
            transaction_type=PaymentTransaction.TYPE_REFUND,
            direction=PaymentTransaction.DIRECTION_OUT,
            amount=Decimal('50.00'),
            related_order=self.order,
            related_customer=self.customer,
        ).exists())

    def test_collect_order_payment_stores_overpayment_as_customer_credit(self):
        collect_order_payment(order=self.order, amount=Decimal('500.00'), cash_account=self.cash, user=self.user)
        self.order.refresh_from_db()
        self.customer.refresh_from_db()
        self.cash.refresh_from_db()

        self.assertEqual(self.order.paid_amount, Decimal('500.00'))
        self.assertEqual(self.order.remaining_amount, Decimal('0.00'))
        self.assertEqual(self.customer.opening_balance, Decimal('200.00'))
        self.assertEqual(build_customer_statement(self.customer)['current_balance'], Decimal('100.00'))
        self.assertEqual(self.cash.balance, Decimal('1500.00'))
        self.assertTrue(PaymentTransaction.objects.filter(
            transaction_type=PaymentTransaction.TYPE_CUSTOMER_PAYMENT,
            direction=PaymentTransaction.DIRECTION_IN,
            amount=Decimal('100.00'),
            related_customer=self.customer,
            related_order__isnull=True,
        ).exists())

    def test_customer_statement_includes_orders_payments_refunds_and_running_balance(self):
        self.order.paid_amount = Decimal('0.00')
        self.order.remaining_amount = Decimal('500.00')
        self.order.save(update_fields=['paid_amount', 'remaining_amount'])
        record_customer_payment(order=None, customer=self.customer, amount=Decimal('200.00'), cash_account=self.cash, user=self.user)
        collect_order_payment(order=self.order, amount=Decimal('100.00'), cash_account=self.cash, user=self.user)
        record_customer_refund_payment(
            customer=self.customer,
            amount=Decimal('50.00'),
            cash_account=self.cash,
            user=self.user,
        )

        statement = build_customer_statement(self.customer)

        self.assertEqual(statement['current_balance'], Decimal('450.00'))
        self.assertEqual(statement['total_debit'], Decimal('750.00'))
        self.assertEqual(statement['total_credit'], Decimal('300.00'))
        self.assertEqual(statement['entries'][-1]['balance'], Decimal('450.00'))

    def test_customer_statement_view_displays_customer_details_and_balance_parts(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('finance:customer_statement'), {'customer': self.customer.pk})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'بيانات العميل')
        self.assertContains(response, 'Test Customer')
        self.assertContains(response, '01000000001')
        self.assertContains(response, 'رصيد فواتير مفتوحة')
        self.assertContains(response, 'رصيد افتتاحي متبق')

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
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.opening_balance, Decimal('200.00'))

        response = self.client.post(reverse('finance:transaction_delete', kwargs={'pk': tx.pk}))

        self.assertRedirects(response, reverse('finance:transactions'))
        self.cash.refresh_from_db()
        self.assertEqual(self.cash.balance, Decimal('1000.00'))
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.opening_balance, Decimal('200.00'))
        self.assertFalse(PaymentTransaction.objects.filter(pk=tx.pk).exists())

    def test_transaction_delete_reopens_related_order_balance(self):
        self.client.force_login(self.user)
        tx = collect_order_payment(
            order=self.order,
            amount=Decimal('200.00'),
            cash_account=self.cash,
            user=self.user,
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.remaining_amount, Decimal('200.00'))

        response = self.client.post(reverse('finance:transaction_delete', kwargs={'pk': tx.pk}))

        self.assertRedirects(response, reverse('finance:transactions'))
        self.order.refresh_from_db()
        self.cash.refresh_from_db()
        self.assertEqual(self.order.paid_amount, Decimal('100.00'))
        self.assertEqual(self.order.remaining_amount, Decimal('400.00'))
        self.assertEqual(self.order.payment_status, Order.PAYMENT_PARTIAL)
        self.assertEqual(self.cash.balance, Decimal('1000.00'))

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

    def test_cash_account_statement_defaults_to_cash_drawer(self):
        self.client.force_login(self.user)
        cash_drawer = CashAccount.get_cash_drawer()

        response = self.client.get(reverse('finance:cash_account_statement'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['account'], cash_drawer)
        self.assertContains(response, 'بيانات الخزنة')
        self.assertContains(response, cash_drawer.name)

    def test_cash_account_statement_accepts_selected_account(self):
        self.client.force_login(self.user)
        collect_order_payment(order=self.order, amount=Decimal('200.00'), cash_account=self.cash, user=self.user)
        add_expense(amount=Decimal('150.00'), cash_account=self.cash, user=self.user, notes='Office rent')

        response = self.client.get(reverse('finance:cash_account_statement'), data={
            'cash_account': self.cash.pk,
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['account'], self.cash)
        self.assertContains(response, 'إجمالي الداخل')
        self.assertContains(response, 'إجمالي الخارج')
        self.assertContains(response, 'Office rent')
