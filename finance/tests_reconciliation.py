import json
from decimal import Decimal
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from accounts.models import User
from audit.models import AuditLog
from customers.models import Customer
from inventory.models import Stock, StockMovement
from orders.models import Order, OrderItem
from returns import tests_edit as return_tests
from returns.models import SalesReturn
from returns.services import cancel_sales_return

from .models import PaymentTransaction
from .reconciliation import inspect_order_return_balance
from .services import build_customer_statement, collect_order_payment


class ReturnBalanceReconciliationTests(TestCase):
    make_return = return_tests.SalesReturnEditTests.make_return
    edit = return_tests.SalesReturnEditTests.edit

    def setUp(self):
        return_tests.SalesReturnEditTests.setUp(self)
        self.sales_return = self.make_return()
        collect_order_payment(order=self.order, amount=100, cash_account=self.cash, user=self.user)
        self.order.refresh_from_db()
        self.order.remaining_amount = Decimal(800)
        self.order.save(update_fields=['remaining_amount'])
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.report = str(Path(self.temporary.name) / 'review.json')

    def review(self, **kwargs):
        call_command('reconcile_customer_returns', customer=self.customer.pk, output=self.report,
                     stdout=StringIO(), **kwargs)
        return json.loads(Path(self.report).read_text(encoding='utf-8'))

    def apply(self, **kwargs):
        options = {'customer': self.customer.pk, 'report': self.report, 'actor': self.user.username,
                   'order_ids': [self.order.pk], 'apply': True, 'stdout': StringIO()}
        options.update(kwargs)
        call_command('reconcile_customer_returns', **options)

    def test_review_is_read_only_and_reports_exact_legacy_return_difference(self):
        before_audits = AuditLog.objects.count()
        report = self.review()
        row = report['orders'][0]
        self.assertEqual(Decimal(row['remaining_before']), Decimal(800))
        self.assertEqual(Decimal(row['remaining_expected']), Decimal(500))
        self.assertEqual(row['problems'], [])
        self.assertEqual(Decimal(report['balance_before']), Decimal(800))
        self.assertEqual(Decimal(report['balance_after_verified_repairs']), Decimal(500))
        self.order.refresh_from_db()
        self.assertEqual(self.order.remaining_amount, Decimal(800))
        self.assertEqual(AuditLog.objects.count(), before_audits)

    def test_repair_corrects_invoice_and_statement_without_touching_cash_stock_or_opening(self):
        self.review()
        self.cash.refresh_from_db()
        cash_before = self.cash.balance
        stock_before = list(Stock.objects.values_list('pk', 'quantity'))
        payments_before = PaymentTransaction.objects.count()
        movements_before = StockMovement.objects.count()
        opening_before = self.customer.opening_balance
        self.apply()
        self.order.refresh_from_db()
        self.cash.refresh_from_db()
        self.customer.refresh_from_db()
        self.assertEqual(self.order.remaining_amount, Decimal(500))
        statement = build_customer_statement(self.customer)
        self.assertEqual(statement['current_balance'], Decimal(500))
        self.assertEqual(statement['statement_opening_balance'], Decimal(0))
        self.assertEqual(self.cash.balance, cash_before)
        self.assertEqual(list(Stock.objects.values_list('pk', 'quantity')), stock_before)
        self.assertEqual(PaymentTransaction.objects.count(), payments_before)
        self.assertEqual(StockMovement.objects.count(), movements_before)
        self.assertEqual(self.customer.opening_balance, opening_before)
        self.assertTrue(AuditLog.objects.filter(notes='Verified legacy return balance reconciliation').exists())

    def test_cancellation_is_blocked_before_repair_and_correct_after_repair(self):
        payments_before = PaymentTransaction.objects.count()
        movements_before = StockMovement.objects.count()
        with self.assertRaisesMessage(ValidationError, 'رصيد الفاتورة غير متطابق'):
            cancel_sales_return(sales_return=self.sales_return, user=self.user)
        self.assertEqual(PaymentTransaction.objects.count(), payments_before)
        self.assertEqual(StockMovement.objects.count(), movements_before)
        self.review()
        self.apply()
        cancel_sales_return(sales_return=self.sales_return, user=self.user)
        self.assertEqual(build_customer_statement(self.customer)['current_balance'], Decimal(800))

    def test_edit_is_also_blocked_until_legacy_debt_is_repaired(self):
        with self.assertRaisesMessage(ValidationError, 'رصيد الفاتورة غير متطابق'):
            self.edit(self.sales_return, quantity=2)

    def test_changed_invoice_invalidates_report(self):
        self.review()
        collect_order_payment(order=self.order, amount=20, cash_account=self.cash, user=self.user)
        with self.assertRaisesMessage(CommandError, 'changed after review'):
            self.apply()
        self.order.refresh_from_db()
        self.assertEqual(self.order.remaining_amount, Decimal(780))

    def test_missing_receipts_are_reported_and_cannot_be_repaired_automatically(self):
        PaymentTransaction.objects.filter(related_order=self.order).delete()
        report = self.review()
        self.assertIn('paid_amount_does_not_match_receipts', report['orders'][0]['problems'])
        with self.assertRaisesMessage(CommandError, 'manual review'):
            self.apply()

    def test_mismatched_return_cash_links_are_blocked(self):
        self.sales_return.debt_reduction = Decimal(200)
        self.sales_return.save(update_fields=['debt_reduction'])
        result = inspect_order_return_balance(self.order)
        self.assertIn(f'return_{self.sales_return.pk}:cash_links_mismatch', result['problems'])

    def test_apply_requires_explicit_order_actor_and_review_report(self):
        for options in ({'report': None}, {'actor': None}, {'order_ids': None}):
            with self.subTest(options=options), self.assertRaises(CommandError):
                self.apply(**options)

    def test_report_cannot_be_applied_to_another_customer(self):
        self.review()
        other = Customer.objects.create(name='Other review customer', created_by=self.user)
        with self.assertRaisesMessage(CommandError, 'does not match'):
            self.apply(customer=other.pk)

    def test_sales_actor_cannot_apply_repairs(self):
        self.review()
        sales = User.objects.create_user(username='reconcile-sales', role='sales')
        with self.assertRaisesMessage(CommandError, 'active manager'):
            self.apply(actor=sales.username)

    def test_rerunning_old_report_never_applies_the_difference_twice(self):
        self.review()
        self.apply()
        with self.assertRaisesMessage(CommandError, 'changed after review'):
            self.apply()
        self.order.refresh_from_db()
        self.assertEqual(self.order.remaining_amount, Decimal(500))

    def test_changed_report_target_cannot_override_recomputed_balance(self):
        report = self.review()
        report['orders'][0]['remaining_expected'] = '0'
        Path(self.report).write_text(json.dumps(report), encoding='utf-8')
        self.apply()
        self.order.refresh_from_db()
        self.assertEqual(self.order.remaining_amount, Decimal(500))

    def test_cancelled_return_credit_is_not_subtracted_again(self):
        self.order.remaining_amount = Decimal(500)
        self.order.save(update_fields=['remaining_amount'])
        cancel_sales_return(sales_return=self.sales_return, user=self.user)
        self.order.refresh_from_db()
        row = inspect_order_return_balance(self.order)
        self.assertEqual(row['problems'], [])
        self.assertEqual(Decimal(row['remaining_expected']), Decimal(800))
        self.assertFalse(row['needs_repair'])
        self.sales_return.refresh_from_db()
        self.assertEqual(self.sales_return.status, SalesReturn.STATUS_CANCELLED)

    def test_batch_is_not_partially_repaired_when_another_selected_order_changed(self):
        first = self.order
        self.order = Order.objects.create(order_number='RECONCILE-SECOND', customer=self.customer,
                                          warehouse=self.warehouse, status=Order.STATUS_COMPLETED,
                                          total=300, remaining_amount=300, created_by=self.user)
        self.order_item = OrderItem.objects.create(order=self.order, variant=self.variant, quantity=1,
                                                   unit_price=300, total=300)
        self.make_return()
        self.review()
        self.order.remaining_amount = Decimal(100)
        self.order.save(update_fields=['remaining_amount'])
        with self.assertRaisesMessage(CommandError, 'changed after review'):
            self.apply(order_ids=[first.pk, self.order.pk])
        first.refresh_from_db()
        self.assertEqual(first.remaining_amount, Decimal(800))

    def test_ambiguous_excess_collection_blocks_cancellation_even_at_zero_remaining(self):
        self.order.paid_amount = Decimal(900)
        self.order.remaining_amount = Decimal(0)
        self.order.save(update_fields=['paid_amount', 'remaining_amount'])
        with self.assertRaisesMessage(ValidationError, 'رصيد الفاتورة غير متطابق'):
            cancel_sales_return(sales_return=self.sales_return, user=self.user)

    def test_shared_return_cash_payment_is_not_treated_as_verified(self):
        self.order.remaining_amount = Decimal(500)
        self.order.save(update_fields=['remaining_amount'])
        second = self.make_return(quantity=1)
        second.financial_transactions.add(PaymentTransaction.objects.get(related_order=self.order))
        row = inspect_order_return_balance(self.order)
        self.assertTrue(row['problems'])
