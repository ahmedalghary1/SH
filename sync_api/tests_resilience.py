from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from unittest import skipUnless

from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase

from accounts.models import Branch, User
from config.branching import reset_current_branch, set_current_branch
from customers.models import Customer
from finance.models import CashAccount
from finance.models import PaymentTransaction
from inventory.models import Stock, Warehouse
from inventory.services import stock_in
from invoices.models import Invoice
from orders.models import Order
from products.models import Product, ProductVariant
from sync_api.auth import make_token
from sync_api.models import SyncOperation
from sync_api.services import process_operation


def customer_operation(key='safe-key', name='Offline customer'):
    return {'idempotency_key': key, 'device_id': 'test-device', 'entity_type': 'customer',
            'operation_type': 'create', 'local_uuid': key,
            'payload': {'customer': {'name': name, 'phone': '01099999999'}}}


class SyncResilienceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(name='Sync branch', code='SYNC-SAFE')
        cls.manager = User.objects.create_user(username='safe-sync', role='manager', branch=cls.branch)
        cls.warehouse = User.objects.create_user(username='safe-warehouse', role='warehouse', branch=cls.branch)

    def sale_operation(self, action='confirm'):
        warehouse = Warehouse.objects.create(name='Offline warehouse', branch=self.branch)
        customer = Customer.objects.create(name='Offline sale customer', branch=self.branch)
        product = Product.objects.create(name='Offline product', sku='OFFLINE-SAFE', branch=self.branch)
        variant = ProductVariant.objects.create(product=product, variant_sku='OFFLINE-SAFE-V',
                                               cost_price=Decimal('10'), retail_price=Decimal('30'), branch=self.branch)
        token = set_current_branch(self.branch.pk)
        try:
            stock_in(variant=variant, warehouse=warehouse, quantity=10, user=self.manager, unit_cost=Decimal('10'))
        finally:
            reset_current_branch(token)
        operation = customer_operation('safe-sale')
        operation.update(entity_type='order', payload={'order': {'customer_server_id': customer.pk,
            'warehouse': warehouse.pk, 'action': action, 'payment_method': 'cash', 'document_type': 'sale'},
            'items': [{'variant_id': variant.pk, 'warehouse_id': warehouse.pk, 'quantity': 1, 'unit_price': '30'}]})
        return operation

    def test_confirmed_offline_sale_creates_one_invoice_and_one_receipt(self):
        operation = self.sale_operation()
        first = process_operation(operation, self.manager)
        self.assertEqual(first['status'], 'success')
        self.assertEqual(process_operation(operation, self.manager), first)
        self.assertEqual(Invoice.all_objects.filter(branch=self.branch).count(), 1)
        self.assertEqual(PaymentTransaction.all_objects.filter(branch=self.branch).count(), 1)
        self.assertEqual(Stock.all_objects.get(branch=self.branch).quantity, 9)

    def test_offline_new_invoice_action_holds_without_moving_stock_or_cash(self):
        operation = self.sale_operation('new_invoice')
        result = process_operation(operation, self.manager)
        self.assertEqual(result['status'], 'success')
        self.assertEqual(Order.all_objects.get(branch=self.branch).status, Order.STATUS_DRAFT)
        self.assertFalse(Invoice.all_objects.filter(branch=self.branch).exists())
        self.assertFalse(PaymentTransaction.all_objects.filter(branch=self.branch).exists())
        self.assertEqual(Stock.all_objects.get(branch=self.branch).quantity, 10)

    def test_fractional_offline_quantity_has_no_business_effect(self):
        operation = self.sale_operation()
        operation['payload']['items'][0]['quantity'] = 1.5
        self.assertEqual(process_operation(operation, self.manager)['status'], 'failed_conflict')
        self.assertFalse(Order.all_objects.filter(branch=self.branch).exists())
        self.assertEqual(Stock.all_objects.get(branch=self.branch).quantity, 10)

    def test_status_update_cannot_reset_a_confirmed_invoice_to_draft(self):
        operation = self.sale_operation()
        result = process_operation(operation, self.manager)
        operation = customer_operation('unsafe-status')
        operation.update(entity_type='order', operation_type='update', payload={'order': {'server_id': result['server_id'], 'status': 'draft'}})
        self.assertEqual(process_operation(operation, self.manager)['status'], 'failed_conflict')
        self.assertEqual(Order.all_objects.get(pk=result['server_id']).status, Order.STATUS_CONFIRMED)

    def test_retry_returns_original_result_without_duplicate_customer(self):
        operation = customer_operation()
        first = process_operation(operation, self.manager)
        second = process_operation(operation, self.manager)
        self.assertEqual(first['status'], 'success')
        self.assertEqual(second, first)
        self.assertEqual(Customer.all_objects.filter(branch=self.branch).count(), 1)
        self.assertEqual(SyncOperation.all_objects.count(), 1)

    def test_same_key_with_changed_payload_is_rejected(self):
        process_operation(customer_operation(), self.manager)
        result = process_operation(customer_operation(name='Changed content'), self.manager)
        self.assertEqual(result['status'], 'failed_conflict')
        self.assertEqual(Customer.all_objects.get(branch=self.branch).name, 'Offline customer')

    def test_other_branch_cannot_use_an_existing_receipt(self):
        first = process_operation(customer_operation(), self.manager)
        branch = Branch.objects.create(name='Other branch', code='SYNC-OTHER')
        user = User.objects.create_user(username='other-sync', role='manager', branch=branch)
        second = process_operation(customer_operation(), user)
        self.assertEqual(first['status'], 'success')
        self.assertEqual(second['status'], 'failed_conflict')
        self.assertNotIn('server_id', second)
        self.assertFalse(Customer.all_objects.filter(branch=branch).exists())

    def test_warehouse_cannot_create_cash_movements(self):
        operation = customer_operation()
        operation.update(entity_type='payment', payload={'payment': {'amount': '100'}})
        result = process_operation(operation, self.warehouse)
        self.assertEqual(result['status'], 'failed_conflict')

    def test_offline_customer_receipt_syncs_form_datetime_to_selected_cash_account_once(self):
        customer = Customer.objects.create(name='Receipt customer', branch=self.branch)
        cash = CashAccount.objects.create(name='Receipt drawer', branch=self.branch)
        operation = customer_operation('receipt-from-form')
        operation.update(
            entity_type='payment',
            payload={
                'original_url': '/finance/transactions/collection/',
                'payment': {
                    'customer': str(customer.pk), 'cash_account': str(cash.pk),
                    'amount': '75.00', 'transaction_date': '2026-10-19T09:25',
                    'notes': 'customer receipt', 'allowed_discount': '0',
                },
            },
        )
        first = process_operation(operation, self.manager)
        self.assertEqual(first['status'], 'success', first)
        self.assertEqual(process_operation(operation, self.manager), first)
        receipt = PaymentTransaction.all_objects.get(pk=first['server_id'])
        self.assertEqual(receipt.transaction_date.isoformat(), '2026-10-19')
        self.assertEqual(receipt.transaction_time.strftime('%H:%M'), '09:25')
        self.assertEqual(receipt.cash_account_id, cash.pk)
        cash.refresh_from_db()
        self.assertEqual(cash.balance, Decimal('75.00'))
        self.assertFalse(SyncOperation.all_objects.exists())

    def test_invalid_customer_money_and_missing_reference_have_no_side_effect(self):
        operation = customer_operation()
        operation['payload']['customer']['credit_limit'] = 'NaN'
        result = process_operation(operation, self.manager)
        self.assertEqual(result['status'], 'failed_conflict')
        self.assertFalse(Customer.all_objects.filter(branch=self.branch).exists())
        operation = customer_operation('missing-product')
        operation.update(entity_type='stock', payload={'original_url': '/inventory/movements/out/', 'stock': {'variant': '99999999', 'warehouse': '99999999', 'quantity': '1'}})
        self.assertEqual(process_operation(operation, self.manager)['status'], 'failed_conflict')

    def test_cached_page_scope_is_rejected_after_account_or_branch_change(self):
        self.client.force_login(self.manager)
        response = self.client.get('/api/sync/session/', HTTP_X_PWA_SCOPE='u999-b999-rmanager-s0')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'scope_changed')

    def test_session_refresh_supplies_csrf_and_scope(self):
        self.client.force_login(self.manager)
        response = self.client.get('/api/sync/session/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('csrf_token', response.json())
        self.assertEqual(response.json()['scope'], f'u{self.manager.pk}-b{self.branch.pk}-rmanager-s0')

    def test_calendar_invalid_since_and_oversized_branch_header_are_client_errors(self):
        superuser = User.objects.create_superuser(username='sync-root', password='test')
        auth = {'HTTP_AUTHORIZATION': 'Bearer ' + make_token(superuser)}
        response = self.client.get('/api/sync/bootstrap/', HTTP_X_BRANCH_ID='9' * 100, **auth)
        self.assertEqual(response.status_code, 400)
        response = self.client.get('/api/sync/changes/', {'since': '2026-02-30T00:00'}, **auth)
        self.assertEqual(response.status_code, 400)
        self.client.force_login(superuser)
        response = self.client.get('/api/sync/changes-browser/', {'since': '2026-02-30T00:00'})
        self.assertEqual(response.status_code, 400)


@skipUnless(connection.vendor == 'postgresql', 'PostgreSQL concurrent transaction test')
class ConcurrentSyncTests(TransactionTestCase):
    def test_two_requests_with_the_same_key_commit_once(self):
        branch = Branch.objects.create(name='Concurrent branch', code='SYNC-CONCURRENT')
        user = User.objects.create_user(username='concurrent-sync', role='manager', branch=branch)

        def push(_):
            close_old_connections()
            try:
                return process_operation(customer_operation(), user)
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(push, range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0]['status'], 'success')
        self.assertEqual(Customer.all_objects.filter(branch=branch).count(), 1)
        self.assertEqual(SyncOperation.all_objects.filter(branch=branch).count(), 1)
