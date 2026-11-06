from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from customers.services import get_customer_summary
from finance.models import PaymentTransaction
from finance.reconciliation import inspect_order_return_balance
from finance.services import (
    build_customer_statement,
    collect_order_payment,
    record_customer_payment,
)
from inventory.models import Stock, StockMovement
from orders.models import Order, OrderItem

from . import tests_edit as edit_tests
from .forms import CompleteReturnForm
from .models import ReturnAccountSettlement, SalesReturn
from .services import approve_sales_return, cancel_sales_return, complete_sales_return
from .settlements import convert_unpaid_refund_to_account, refund_account_review


class UnpaidRefundSettlementTests(TestCase):
    make_return = edit_tests.SalesReturnEditTests.make_return
    edit = edit_tests.SalesReturnEditTests.edit

    def setUp(self):
        edit_tests.SalesReturnEditTests.setUp(self)
        self.customer.opening_balance = Decimal(6470)
        self.customer.save(update_fields=['opening_balance'])
        record_customer_payment(order=None, customer=self.customer, amount=6470,
                                cash_account=self.cash, user=self.user)
        self.order.total = Decimal(44210)
        self.order.remaining_amount = Decimal(44210)
        self.order.save(update_fields=['total', 'remaining_amount'])
        self.order_item.unit_price = Decimal(4800)
        self.order_item.total = Decimal(14400)
        self.order_item.save(update_fields=['unit_price', 'total'])
        collect_order_payment(order=self.order, amount=44000, cash_account=self.cash, user=self.user)
        self.new_order = Order.objects.create(
            order_number='NEW-17480', customer=self.customer, warehouse=self.warehouse,
            status=Order.STATUS_COMPLETED, total=17480, remaining_amount=17480, created_by=self.user,
        )
        OrderItem.objects.create(order=self.new_order, variant=self.exchange_variant,
                                 quantity=1, unit_price=17480, total=17480)
        collect_order_payment(order=self.new_order, amount=12500, cash_account=self.cash, user=self.user)
        self.sales_return = self.make_return()

    def convert(self, fingerprint=None):
        return convert_unpaid_refund_to_account(
            sales_return=self.sales_return, user=self.user,
            fingerprint=fingerprint or refund_account_review(self.sales_return)['fingerprint'],
            reason='المحاسب أكد عدم صرف 4590 للعميل',
        )

    def test_exact_customer_example_is_4980_before_and_390_after(self):
        review = refund_account_review(self.sales_return)
        self.assertEqual(Decimal(review['amount']), Decimal(4590))
        self.assertEqual(Decimal(review['balance_before']), Decimal(4980))
        self.assertEqual(Decimal(review['balance_after']), Decimal(390))
        self.convert()
        statement = build_customer_statement(self.customer)
        self.assertEqual(statement['current_balance'], Decimal(390))
        self.assertEqual(statement['statement_opening_balance'], Decimal(6470))
        self.assertFalse(any(entry.get('payment') and entry['payment'].transaction_type == PaymentTransaction.TYPE_REFUND
                             for entry in statement['entries']))
        self.assertEqual(len([entry for entry in statement['entries'] if entry.get('sales_return')]), 1)
        self.new_order.refresh_from_db()
        self.assertEqual(self.new_order.remaining_amount, Decimal(390))
        self.assertEqual(get_customer_summary(self.customer)['total_remaining'], Decimal(390))
        self.assertEqual(get_customer_summary(self.customer)['total_paid'], Decimal(62970))
        self.assertEqual(inspect_order_return_balance(self.new_order)['problems'], [])
        self.order.refresh_from_db()
        self.assertEqual(inspect_order_return_balance(self.order)['problems'], [])

    def test_original_cash_account_is_corrected_without_touching_return_stock(self):
        self.cash.refresh_from_db()
        old_cash = self.cash.balance
        before = list(Stock.objects.values_list('pk', 'quantity'))
        movement_count = StockMovement.objects.count()
        self.convert()
        self.cash.refresh_from_db()
        self.sales_return.refresh_from_db()
        self.assertEqual(self.cash.balance, old_cash + Decimal(4590))
        self.assertEqual(list(Stock.objects.values_list('pk', 'quantity')), before)
        self.assertEqual(StockMovement.objects.count(), movement_count)
        self.assertEqual(self.sales_return.status, SalesReturn.STATUS_COMPLETED)
        self.assertEqual(self.sales_return.refund_amount, Decimal(4800))

    def test_second_conversion_is_idempotent(self):
        fingerprint = refund_account_review(self.sales_return)['fingerprint']
        self.convert(fingerprint)
        count = PaymentTransaction.objects.count()
        self.convert(fingerprint)
        self.assertEqual(PaymentTransaction.objects.count(), count)
        self.assertEqual(build_customer_statement(self.customer)['current_balance'], Decimal(390))

    def test_payment_after_preview_blocks_stale_correction(self):
        fingerprint = refund_account_review(self.sales_return)['fingerprint']
        collect_order_payment(order=self.new_order, amount=20, cash_account=self.cash, user=self.user)
        count = PaymentTransaction.objects.count()
        with self.assertRaisesMessage(ValidationError, 'تغيرت بيانات الحساب'):
            self.convert(fingerprint)
        self.assertEqual(PaymentTransaction.objects.count(), count)
        self.assertFalse(ReturnAccountSettlement.objects.exists())

    def test_cancel_after_conversion_reverses_account_allocation_without_another_cash_movement(self):
        self.convert()
        self.cash.refresh_from_db()
        cash_before = self.cash.balance
        cancel_sales_return(sales_return=self.sales_return, user=self.user)
        self.cash.refresh_from_db()
        self.assertEqual(self.cash.balance, cash_before)
        self.assertEqual(build_customer_statement(self.customer)['current_balance'], Decimal(5190))
        self.assertEqual(get_customer_summary(self.customer)['total_remaining'], Decimal(5190))
        self.new_order.refresh_from_db()
        self.assertEqual(self.new_order.paid_amount, Decimal(12500))
        self.assertEqual(self.new_order.remaining_amount, Decimal(4980))
        self.assertEqual(inspect_order_return_balance(self.new_order)['problems'], [])

    def test_excess_becomes_customer_credit_when_other_invoices_are_settled(self):
        collect_order_payment(order=self.new_order, amount=4980, cash_account=self.cash, user=self.user)
        self.convert()
        self.assertEqual(build_customer_statement(self.customer)['current_balance'], Decimal(-4590))
        self.assertEqual(get_customer_summary(self.customer)['total_remaining'], Decimal(-4590))
        cancel_sales_return(sales_return=self.sales_return, user=self.user)
        self.assertEqual(build_customer_statement(self.customer)['current_balance'], Decimal(210))

    def test_settled_return_amount_cannot_be_changed_without_reversing_settlement(self):
        self.convert()
        self.sales_return.refresh_from_db()
        with self.assertRaisesMessage(ValidationError, 'تمت تسويته'):
            self.edit(self.sales_return, quantity=2)
        self.edit(self.sales_return, quantity=1, reason='Updated notes only')
        self.assertEqual(build_customer_statement(self.customer)['current_balance'], Decimal(390))

    def test_target_invoice_cannot_be_cancelled_while_return_settlement_is_active(self):
        from orders.services import cancel_order

        self.convert()
        with self.assertRaisesMessage(ValidationError, 'تسوية مرتجع'):
            cancel_order(order=self.new_order, user=self.user)

    def test_future_account_completion_does_not_create_automatic_cash_refund(self):
        cancel_sales_return(sales_return=self.sales_return, user=self.user)
        self.cash.refresh_from_db()
        cash_before = self.cash.balance
        draft = self.make_return(completed=False)
        approve_sales_return(sales_return=draft, user=self.user)
        complete_sales_return(sales_return=draft, user=self.user, cash_account=self.cash, settlement_method='account')
        self.cash.refresh_from_db()
        self.assertEqual(self.cash.balance, cash_before)
        self.assertEqual(build_customer_statement(self.customer)['current_balance'], Decimal(390))

    def test_cash_choice_requires_explicit_confirmation(self):
        draft = self.make_return(completed=False)
        form = CompleteReturnForm({'settlement_method': 'cash'}, sales_return=draft)
        self.assertFalse(form.is_valid())
        self.assertIn('confirm_cash_refund', form.errors)
        self.assertTrue(CompleteReturnForm({'settlement_method': 'cash', 'confirm_cash_refund': 'on'},
                                           sales_return=draft).is_valid())

    def test_customer_review_exposes_correction_and_requires_confirmation(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('customers:reconcile_returns', args=[self.customer.pk]))
        url = reverse('returns:correct_unpaid_refund', args=[self.sales_return.pk])
        self.assertContains(response, url)
        response = self.client.get(url)
        self.assertContains(response, '4590.00')
        self.assertContains(response, '390.00')
        token = response.context['form']['review_token'].value()
        data = {'review_token': token, 'reason': 'لم يُصرف المبلغ'}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ReturnAccountSettlement.objects.exists())
        response = self.client.post(url, {**data, 'confirm_not_paid': 'on'}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(build_customer_statement(self.customer)['current_balance'], Decimal(390))

    def test_sales_users_cannot_correct_refund(self):
        sales = User.objects.create_user(username='refund-correction-sales', role='sales')
        self.client.force_login(sales)
        self.assertEqual(self.client.get(reverse('returns:correct_unpaid_refund', args=[self.sales_return.pk])).status_code, 403)
