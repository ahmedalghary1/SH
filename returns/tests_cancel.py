from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import Branch, User
from config.branching import reset_current_branch, set_current_branch
from customers.services import get_customer_summary
from finance.models import CashAccount, PaymentTransaction
from finance.services import (
    build_cash_account_statement,
    build_customer_statement,
    collect_order_payment,
)
from inventory.models import Stock, StockMovement
from inventory.services import sale_stock
from orders.models import Order

from . import tests_edit as edit_tests
from .models import SalesReturn
from .services import (
    approve_sales_return,
    calculate_available_return_quantity,
    cancel_sales_return,
    complete_sales_return,
    update_sales_return,
)


class SalesReturnCancellationTests(TestCase):
    make_return = edit_tests.SalesReturnEditTests.make_return
    edit = edit_tests.SalesReturnEditTests.edit

    def setUp(self):
        edit_tests.SalesReturnEditTests.setUp(self)

    def cancel(self, sales_return, **kwargs):
        return cancel_sales_return(sales_return=sales_return, user=self.user,
                                   revision=sales_return.revision, **kwargs)

    def assert_balance(self, amount):
        statement = build_customer_statement(self.customer)
        self.assertEqual(statement['current_balance'], Decimal(amount))
        self.assertEqual(statement['statement_opening_balance'], Decimal(0))
        self.assertEqual(get_customer_summary(self.customer)['total_remaining'], Decimal(amount))
        return statement

    def test_credit_cancellation_restores_invoice_debt_quantity_and_stock(self):
        sales_return = self.make_return(quantity=2, warehouse=self.target)
        cancelled = self.cancel(sales_return, reason='Customer kept the items')
        self.order.refresh_from_db()
        self.assertEqual(cancelled.status, SalesReturn.STATUS_CANCELLED)
        self.assertEqual(cancelled.cancelled_by, self.user)
        self.assertIsNotNone(cancelled.cancelled_at)
        self.assertEqual(cancelled.cancellation_reason, 'Customer kept the items')
        self.assertEqual(self.order.remaining_amount, Decimal(900))
        self.assertEqual(self.order.status, Order.STATUS_COMPLETED)
        self.assertEqual(calculate_available_return_quantity(self.order_item), 3)
        self.assertEqual(Stock.objects.get(warehouse=self.target, variant=self.variant).quantity, 0)
        self.assertEqual(len(self.assert_balance('900')['entries']), 1)

    def test_cash_cancellation_restores_cash_and_removes_all_return_statement_rows(self):
        sales_return = self.make_return(quantity=3, paid=900)
        self.cancel(sales_return)
        self.cash.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.cash.balance, Decimal(2900))
        self.assertEqual(self.order.paid_amount, Decimal(900))
        self.assertEqual(self.order.remaining_amount, Decimal(0))
        self.assertEqual(self.order.status, Order.STATUS_COMPLETED)
        statement = self.assert_balance('0')
        self.assertEqual(statement['total_debit'], Decimal(900))
        self.assertEqual(statement['total_credit'], Decimal(900))
        linked_ids = set(sales_return.financial_transactions.values_list('pk', flat=True))
        self.assertEqual(len(linked_ids), 2)
        self.assertFalse(any(entry.get('sales_return') for entry in statement['entries']))
        self.assertFalse(any(entry.get('payment') and entry['payment'].pk in linked_ids for entry in statement['entries']))
        self.assertEqual(get_customer_summary(self.customer)['total_paid'], Decimal(900))
        self.assertEqual(build_cash_account_statement(self.cash)['current_balance'], Decimal(2900))

    def test_mixed_return_restores_only_cancelled_debt_and_cash_parts(self):
        sales_return = self.make_return(quantity=2, paid=600)
        self.cancel(sales_return)
        self.cash.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.cash.balance, Decimal(2600))
        self.assertEqual(self.order.remaining_amount, Decimal(300))
        self.assertEqual(self.order.payment_status, Order.PAYMENT_PARTIAL)
        self.assert_balance('300')

    def test_cancelling_edited_return_reverses_its_current_net_effect(self):
        sales_return = self.make_return(quantity=2, paid=600)
        sales_return = self.edit(sales_return, quantity=1)
        self.cancel(sales_return)
        self.cash.refresh_from_db()
        self.assertEqual(self.cash.balance, Decimal(2600))
        self.assertEqual(Stock.objects.get(warehouse=self.warehouse, variant=self.variant).quantity, 0)
        self.assert_balance('300')
        self.assertEqual(get_customer_summary(self.customer)['total_paid'], Decimal(600))

    def test_later_invoice_receipt_is_preserved_when_return_is_cancelled(self):
        sales_return = self.make_return(quantity=2)
        receipt = collect_order_payment(order=self.order, amount=300, cash_account=self.cash, user=self.user)
        self.cancel(sales_return)
        statement = self.assert_balance('600')
        self.assertTrue(any(entry.get('payment') == receipt for entry in statement['entries']))

    def test_exchange_cancellation_restores_replacement_stock_and_difference(self):
        sales_return = self.make_return(exchange=True, paid=900)
        self.cancel(sales_return)
        self.cash.refresh_from_db()
        self.assertEqual(self.cash.balance, Decimal(2900))
        self.assertEqual(Stock.objects.get(warehouse=self.warehouse, variant=self.variant).quantity, 0)
        self.assertEqual(Stock.objects.get(warehouse=self.warehouse, variant=self.exchange_variant).quantity, 5)
        self.assert_balance('0')

    def test_edited_exchange_with_refund_difference_cancels_correctly(self):
        sales_return = self.make_return(exchange=True, paid=900)
        exchange = sales_return.exchange_items.get()
        sales_return = self.edit(sales_return, exchanges=[{
            'item_id': exchange.pk, 'old_order_item': self.order_item,
            'new_product_variant': self.exchange_variant, 'quantity': 1, 'new_unit_price': 280,
        }])
        self.cancel(sales_return)
        self.cash.refresh_from_db()
        self.assertEqual(self.cash.balance, Decimal(2900))
        self.assert_balance('0')

    def test_every_original_cash_account_is_reversed_separately(self):
        sales_return = self.make_return(paid=900)
        other = CashAccount.objects.create(name='Second return cash', balance=1000)
        item = sales_return.items.get()
        sales_return = update_sales_return(
            sales_return=sales_return, user=self.user, revision=sales_return.revision,
            items=[{'item_id': item.pk, 'original_order_item': self.order_item, 'quantity': 2,
                    'condition': 'good', 'return_to_stock': True}], cash_account=other,
        )
        self.cancel(sales_return)
        self.cash.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(self.cash.balance, Decimal(2900))
        self.assertEqual(other.balance, Decimal(1000))
        self.assert_balance('0')

    def test_stock_shortage_rolls_back_the_entire_cancellation(self):
        sales_return = self.make_return(quantity=2, paid=900)
        sale_stock(variant=self.variant, warehouse=self.warehouse, quantity=1, user=self.user)
        before_payments = PaymentTransaction.objects.count()
        before_movements = StockMovement.objects.count()
        with self.assertRaises(ValidationError):
            self.cancel(sales_return)
        sales_return.refresh_from_db()
        self.assertEqual(sales_return.status, SalesReturn.STATUS_COMPLETED)
        self.assertIsNone(sales_return.cancelled_at)
        self.assertEqual(PaymentTransaction.objects.count(), before_payments)
        self.assertEqual(StockMovement.objects.count(), before_movements)

    def test_insufficient_exchange_cash_rolls_back_stock_reversal(self):
        sales_return = self.make_return(exchange=True, paid=900)
        self.cash.balance = Decimal(0)
        self.cash.save(update_fields=['balance'])
        with self.assertRaisesMessage(ValidationError, 'رصيد الخزنة غير كاف'):
            self.cancel(sales_return)
        sales_return.refresh_from_db()
        self.assertEqual(sales_return.status, SalesReturn.STATUS_COMPLETED)
        self.assertEqual(Stock.objects.get(warehouse=self.warehouse, variant=self.variant).quantity, 1)
        self.assertEqual(Stock.objects.get(warehouse=self.warehouse, variant=self.exchange_variant).quantity, 4)

    def test_other_returns_remain_active_and_final_cancel_restores_original_status(self):
        self.order.status = Order.STATUS_CONFIRMED
        self.order.save(update_fields=['status'])
        first = self.make_return(quantity=1)
        second = self.make_return(quantity=2)
        self.cancel(first)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_PARTIALLY_RETURNED)
        self.assertEqual(calculate_available_return_quantity(self.order_item), 1)
        self.assert_balance('300')
        self.cancel(second)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_CONFIRMED)
        self.assert_balance('900')

    def test_draft_and_approved_returns_cancel_without_posting_effects(self):
        for approved in (False, True):
            with self.subTest(approved=approved):
                sales_return = self.make_return(completed=False)
                if approved:
                    approve_sales_return(sales_return=sales_return, user=self.user)
                    sales_return.refresh_from_db()
                self.cancel(sales_return)
        self.assertFalse(PaymentTransaction.objects.exists())
        self.assertFalse(StockMovement.objects.exists())
        self.assert_balance('900')

    def test_repeated_cancellation_has_no_additional_effect(self):
        sales_return = self.make_return(paid=900)
        self.cancel(sales_return)
        transactions = PaymentTransaction.objects.count()
        movements = StockMovement.objects.count()
        self.cancel(sales_return)
        self.assertEqual(PaymentTransaction.objects.count(), transactions)
        self.assertEqual(StockMovement.objects.count(), movements)
        self.assert_balance('0')

    def test_stale_revision_is_rejected_before_any_effect(self):
        sales_return = self.make_return()
        self.edit(sales_return, quantity=2)
        with self.assertRaisesMessage(ValidationError, 'أعد تحميل الصفحة'):
            self.cancel(sales_return)

    def test_cancelled_return_cannot_be_edited_or_completed_again(self):
        sales_return = self.make_return()
        cancelled = self.cancel(sales_return)
        with self.assertRaisesMessage(ValidationError, 'مرتجع ملغى'):
            self.edit(cancelled)
        with self.assertRaises(ValidationError):
            approve_sales_return(sales_return=cancelled, user=self.user)
        with self.assertRaises(ValidationError):
            complete_sales_return(sales_return=cancelled, user=self.user)

    def test_inconsistent_financial_links_prevent_cancellation(self):
        sales_return = self.make_return(paid=900)
        sales_return.financial_transactions.clear()
        with self.assertRaisesMessage(ValidationError, 'مطابقة الحركات المالية'):
            self.cancel(sales_return)

    def test_cross_branch_and_sales_users_cannot_cancel(self):
        sales_return = self.make_return()
        other = Branch.objects.create(code='CANCEL-OTHER', name='Other cancel branch')
        token = set_current_branch(other.pk)
        try:
            with self.assertRaises(ValidationError):
                self.cancel(sales_return)
        finally:
            reset_current_branch(token)
        sales = User.objects.create_user(username='cancel-sales', role='sales')
        with self.assertRaises(ValidationError):
            cancel_sales_return(sales_return=sales_return, user=sales)
        self.client.force_login(sales)
        self.assertEqual(self.client.get(reverse('returns:cancel', args=[sales_return.pk])).status_code, 403)

    def test_confirmation_view_requires_post_and_removes_customer_statement_rows(self):
        sales_return = self.make_return(paid=900)
        self.client.force_login(self.user)
        url = reverse('returns:cancel', args=[sales_return.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        sales_return.refresh_from_db()
        self.assertEqual(sales_return.status, SalesReturn.STATUS_COMPLETED)
        response = self.client.post(url, {'revision': sales_return.revision, 'reason': 'Cancel from page'})
        self.assertRedirects(response, reverse('returns:detail', args=[sales_return.pk]))
        self.assertEqual(self.client.get(reverse('returns:edit', args=[sales_return.pk])).status_code, 404)
        response = self.client.get(reverse('finance:customer_statement'), {'customer': self.customer.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['statement']), 2)
        self.assertEqual(response.context['current_balance'], Decimal(0))
        response = self.client.get(reverse('returns:list'), {'status': 'cancelled'})
        self.assertContains(response, 'ملغى')
        self.assertContains(response, f'#{sales_return.pk}')

    def test_invoice_cancellation_after_return_cancellation_refunds_full_receipt(self):
        from orders.services import cancel_order

        sales_return = self.make_return(paid=900)
        self.cancel(sales_return)
        cancel_order(order=self.order, user=self.user)
        self.cash.refresh_from_db()
        self.assertEqual(self.cash.balance, Decimal(2000))
        self.assert_balance('0')

    def test_invoice_deletion_after_return_cancellation_refunds_full_receipt(self):
        from invoices.services import delete_invoice

        sales_return = self.make_return(paid=900)
        self.cancel(sales_return)
        delete_invoice(invoice=self.invoice, user=self.user)
        self.cash.refresh_from_db()
        self.assertEqual(self.cash.balance, Decimal(2000))
        self.assert_balance('0')

    def test_damaged_and_nonstock_returns_do_not_create_usable_stock_on_cancellation(self):
        for condition in ('damaged', 'needs_review'):
            with self.subTest(condition=condition):
                sales_return = self.make_return(completed=False)
                item = sales_return.items.get()
                item.condition = condition
                item.return_to_stock = False
                item.save(update_fields=['condition', 'return_to_stock'])
                approve_sales_return(sales_return=sales_return, user=self.user)
                complete_sales_return(sales_return=sales_return, user=self.user)
                sales_return.refresh_from_db()
                self.cancel(sales_return)
                self.assertEqual(Stock.objects.get(warehouse=self.warehouse, variant=self.variant).quantity, 0)
                self.assert_balance('900')

    def test_new_return_does_not_restore_status_from_an_older_cancelled_return(self):
        self.order.status = Order.STATUS_CONFIRMED
        self.order.save(update_fields=['status'])
        old = self.make_return()
        self.cancel(old)
        self.order.refresh_from_db()
        self.order.status = Order.STATUS_COMPLETED
        self.order.save(update_fields=['status'])
        first = self.make_return()
        second = self.make_return()
        self.cancel(first)
        self.cancel(second)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_COMPLETED)
