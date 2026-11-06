import time
from decimal import Decimal
from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Branch, User
from audit.models import AuditLog
from customers.models import Customer
from finance import tests_reconciliation as reconciliation_tests
from finance.models import PaymentTransaction
from finance.services import build_customer_statement, collect_order_payment
from inventory.models import Stock, StockMovement
from returns import tests_edit as return_tests


class CustomerReconciliationPageTests(TestCase):
    make_return = return_tests.SalesReturnEditTests.make_return

    def setUp(self):
        reconciliation_tests.ReturnBalanceReconciliationTests.setUp(self)
        self.url = reverse('customers:reconcile_returns', args=[self.customer.pk])
        self.client.force_login(self.user)

    def review(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        return response.context['form']['review_token'].value()

    def submit(self, token=None, **kwargs):
        data = {'review_token': token or self.review(), 'orders': [str(self.order.pk)], 'confirm': 'on'}
        data.update(kwargs)
        return self.client.post(self.url, data, follow=True)

    def test_both_customer_pages_link_to_review_for_manager(self):
        for name in ('customers:detail', 'customers:simple_detail'):
            with self.subTest(name=name):
                response = self.client.get(reverse(name, args=[self.customer.pk]))
                self.assertContains(response, self.url)
                self.assertContains(response, 'مراجعة رصيد المرتجعات')

    def test_review_get_is_read_only_and_displays_comparison(self):
        audits_before = AuditLog.objects.count()
        response = self.client.get(self.url)
        self.assertContains(response, '800.00')
        self.assertContains(response, '500.00')
        self.assertContains(response, 'متاحة للتصحيح')
        self.assertIn('no-store', response['Cache-Control'])
        self.order.refresh_from_db()
        self.assertEqual(self.order.remaining_amount, Decimal(800))
        self.assertEqual(AuditLog.objects.count(), audits_before)

    def test_selected_invoice_is_corrected_and_customer_statement_updates(self):
        stock_before = list(Stock.objects.values_list('pk', 'quantity'))
        movements_before = StockMovement.objects.count()
        payments_before = PaymentTransaction.objects.count()
        response = self.submit()
        self.assertContains(response, 'تم تصحيح رصيد 1 فاتورة')
        self.assertContains(response, 'أرصدة الفواتير متطابقة')
        self.order.refresh_from_db()
        self.assertEqual(self.order.remaining_amount, Decimal(500))
        self.assertEqual(build_customer_statement(self.customer)['current_balance'], Decimal(500))
        self.assertEqual(PaymentTransaction.objects.count(), payments_before)
        self.assertEqual(StockMovement.objects.count(), movements_before)
        self.assertEqual(list(Stock.objects.values_list('pk', 'quantity')), stock_before)

    def test_confirm_and_invoice_selection_are_required(self):
        for values in ({'confirm': ''}, {'orders': []}):
            with self.subTest(values=values):
                response = self.submit(**values)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['form'].errors)
                self.order.refresh_from_db()
                self.assertEqual(self.order.remaining_amount, Decimal(800))

    def test_modified_or_missing_token_never_applies_changes(self):
        token = self.review()
        response = self.submit(token=token + 'modified')
        self.assertContains(response, 'تعذر التحقق من المراجعة')
        response = self.submit(review_token='')
        self.assertTrue(response.context['form'].errors)
        self.order.refresh_from_db()
        self.assertEqual(self.order.remaining_amount, Decimal(800))

    def test_review_is_bound_to_user_and_customer(self):
        token = self.review()
        second = User.objects.create_user(username='second-review-manager', role='manager')
        self.client.force_login(second)
        self.assertContains(self.submit(token=token), 'تعذر التحقق من المراجعة')
        self.client.force_login(self.user)
        other = Customer.objects.create(name='Other GUI review', created_by=self.user)
        self.url = reverse('customers:reconcile_returns', args=[other.pk])
        self.assertContains(self.submit(token=token), 'تعذر التحقق من المراجعة')

    def test_expired_review_is_rejected(self):
        token = self.review()
        with patch('django.core.signing.time.time', return_value=time.time() + 1801):
            response = self.submit(token=token)
        self.assertContains(response, 'انتهت صلاحية المراجعة')
        self.order.refresh_from_db()
        self.assertEqual(self.order.remaining_amount, Decimal(800))

    def test_payment_after_review_forces_fresh_review(self):
        token = self.review()
        collect_order_payment(order=self.order, amount=20, cash_account=self.cash, user=self.user)
        response = self.submit(token=token)
        self.assertContains(response, 'تغيرت بيانات إحدى الفواتير')
        self.order.refresh_from_db()
        self.assertEqual(self.order.remaining_amount, Decimal(780))

    def test_repeated_post_does_not_apply_difference_twice(self):
        token = self.review()
        self.submit(token=token)
        audits_before = AuditLog.objects.filter(notes='Verified legacy return balance reconciliation').count()
        response = self.submit(token=token)
        self.assertContains(response, 'لم يُنفذ أي تصحيح')
        self.order.refresh_from_db()
        self.assertEqual(self.order.remaining_amount, Decimal(500))
        self.assertEqual(AuditLog.objects.filter(notes='Verified legacy return balance reconciliation').count(), audits_before)

    def test_blocked_invoice_is_explained_in_arabic_and_cannot_be_selected(self):
        PaymentTransaction.objects.filter(related_order=self.order).delete()
        response = self.client.get(self.url)
        self.assertContains(response, 'المدفوع المسجل لا يطابق الدفعات المتاحة')
        self.assertNotContains(response, 'name="orders"')
        token = response.context['form']['review_token'].value()
        self.assertTrue(self.submit(token=token).context['form'].errors)

    def test_other_customer_invoice_cannot_be_submitted(self):
        response = self.submit(orders=['999999999'])
        self.assertTrue(response.context['form'].errors)
        self.order.refresh_from_db()
        self.assertEqual(self.order.remaining_amount, Decimal(800))

    def test_sales_user_and_other_branch_manager_cannot_access_review(self):
        sales = User.objects.create_user(username='gui-review-sales', role='sales')
        self.client.force_login(sales)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        response = self.client.get(reverse('customers:simple_detail', args=[self.customer.pk]))
        self.assertNotContains(response, self.url)
        branch = Branch.objects.create(code='GUI-REVIEW', name='Other GUI review branch')
        manager = User.objects.create_user(username='gui-review-manager', role='manager', branch=branch)
        self.client.force_login(manager)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_csrf_is_required_for_correction(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        token = client.get(self.url).context['form']['review_token'].value()
        response = client.post(self.url, {'review_token': token, 'orders': [self.order.pk], 'confirm': 'on'})
        self.assertEqual(response.status_code, 403)
