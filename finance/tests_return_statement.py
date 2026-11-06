from datetime import datetime
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from orders.models import Order
from returns import tests as return_tests
from returns.models import SalesReturn
from returns.services import (
    add_return_item,
    approve_sales_return,
    complete_sales_return,
    create_sales_return,
)

from .models import PaymentTransaction
from .services import (
    build_customer_statement,
    collect_order_payment,
    delete_transaction,
)


class CustomerReturnStatementTests(TestCase):
    def setUp(self):
        return_tests.SalesReturnServiceTests.setUp(self)
        self.order.paid_amount = Decimal(0)
        self.order.remaining_amount = self.order.total
        self.order.save(update_fields=['paid_amount', 'remaining_amount'])

    def complete_return(self, quantity=1, return_datetime=None):
        sales_return = create_sales_return(
            order=self.order, return_type=SalesReturn.TYPE_PARTIAL_RETURN,
            user=self.user, return_datetime=return_datetime,
        )
        add_return_item(sales_return=sales_return, original_order_item=self.order_item, quantity=quantity)
        approve_sales_return(sales_return=sales_return, user=self.user)
        return complete_sales_return(sales_return=sales_return, user=self.user, cash_account=self.cash)

    def assert_statement(self, balance):
        statement = build_customer_statement(self.customer)
        self.assertEqual(statement['current_balance'], Decimal(balance))
        self.assertEqual(statement['statement_opening_balance'], Decimal(0))
        self.assertEqual(statement['entries'][-1]['balance'], Decimal(balance))
        return statement

    def test_credit_return_and_later_receipt_preserve_reduced_debt(self):
        self.complete_return()
        self.assert_statement('600')
        collect_order_payment(order=self.order, amount=100, user=self.user, cash_account=self.cash)
        self.order.refresh_from_db()
        self.assertEqual(self.order.remaining_amount, Decimal(500))
        self.assert_statement('500')

    def test_deleting_later_receipt_preserves_return_credit(self):
        self.complete_return()
        payment = collect_order_payment(order=self.order, amount=100, user=self.user, cash_account=self.cash)
        delete_transaction(payment_transaction=payment, user=self.user)
        self.order.refresh_from_db()
        self.assertEqual(self.order.remaining_amount, Decimal(600))
        self.assert_statement('600')

    def test_reversing_payment_after_return_preserves_return_credit(self):
        collect_order_payment(order=self.order, amount=200, user=self.user, cash_account=self.cash)
        self.complete_return()
        collect_order_payment(order=self.order, amount=-50, user=self.user, cash_account=self.cash)
        self.order.refresh_from_db()
        self.assertEqual(self.order.remaining_amount, Decimal(450))
        self.assert_statement('450')

    def test_partial_paid_return_splits_debt_reduction_and_cash_refund(self):
        collect_order_payment(order=self.order, amount=600, user=self.user, cash_account=self.cash)
        self.complete_return(quantity=2)
        statement = self.assert_statement('0')
        self.assertEqual(sum(e['credit'] for e in statement['entries'] if e.get('sales_return')), Decimal(600))
        self.assertEqual(sum(e['debit'] for e in statement['entries'] if e.get('payment') and e['payment'].transaction_type == PaymentTransaction.TYPE_REFUND), Decimal(300))

    def test_full_paid_return_has_no_artificial_opening_balance(self):
        collect_order_payment(order=self.order, amount=900, user=self.user, cash_account=self.cash)
        self.complete_return(quantity=3)
        self.assert_statement('0')
        self.client.force_login(self.user)
        response = self.client.get(reverse('finance:customer_statement'), {'customer': self.customer.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['current_balance'], Decimal(0))

    def test_backdated_cash_return_and_refund_share_local_date(self):
        collect_order_payment(order=self.order, amount=900, user=self.user, cash_account=self.cash)
        selected = datetime(2026, 10, 10, 0, 30, tzinfo=timezone.get_current_timezone())
        sales_return = self.complete_return(return_datetime=selected)
        refund = PaymentTransaction.objects.get(transaction_type=PaymentTransaction.TYPE_REFUND)
        self.assertEqual(refund.transaction_date, selected.date())
        self.assertEqual(refund.transaction_time, selected.time())
        statement = build_customer_statement(self.customer)
        entry = next(e for e in statement['entries'] if e.get('sales_return') == sales_return)
        self.assertEqual(entry['date'], selected.date())

    def test_return_date_is_local_even_without_cash_refund(self):
        selected = datetime(2026, 10, 10, 0, 30, tzinfo=timezone.get_current_timezone())
        sales_return = self.complete_return(return_datetime=selected)
        self.client.force_login(self.user)
        response = self.client.get(reverse('finance:customer_statement'), {
            'customer': self.customer.pk, 'period': 'custom',
            'date_from': '2026-10-10', 'date_to': '2026-10-10',
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any(e.get('sales_return') == sales_return for e in response.context['statement']))

    def test_same_day_receipt_precedes_later_return_in_running_balance(self):
        sold_at = datetime(2026, 10, 10, 9, tzinfo=timezone.get_current_timezone())
        paid_at = sold_at.replace(hour=10)
        returned_at = sold_at.replace(hour=11)
        Order.objects.filter(pk=self.order.pk).update(created_at=sold_at)
        payment = collect_order_payment(
            order=self.order, amount=900, user=self.user,
            cash_account=self.cash, transaction_date=paid_at,
        )
        sales_return = self.complete_return(return_datetime=returned_at)
        statement = self.assert_statement('0')
        self.assertEqual(
            [(e['debit'], e['credit'], e['balance']) for e in statement['entries']],
            [(Decimal(900), Decimal(0), Decimal(900)),
             (Decimal(0), Decimal(900), Decimal(0)),
             (Decimal(0), Decimal(300), Decimal(-300)),
             (Decimal(300), Decimal(0), Decimal(0))],
        )
        self.assertEqual(statement['entries'][1]['payment'], payment)
        self.assertEqual(statement['entries'][2]['sales_return'], sales_return)

    def test_settling_returned_invoice_does_not_reopen_returned_debt(self):
        self.complete_return()
        collect_order_payment(order=self.order, amount=600, user=self.user, cash_account=self.cash)
        self.order.refresh_from_db()
        self.assertEqual(self.order.remaining_amount, Decimal(0))
        self.assertEqual(self.order.payment_status, Order.PAYMENT_PAID)
        self.assert_statement('0')
