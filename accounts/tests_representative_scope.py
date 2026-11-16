from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from customers.models import Customer
from finance.models import CashAccount
from sync_api.services import process_operation


class RepresentativeScopeTests(TestCase):
    def setUp(self):
        self.rep = User.objects.create_user(username='scope-rep', role='sales')
        self.other = User.objects.create_user(username='scope-other', role='sales')
        self.customer = Customer.objects.create(name='Visible customer', sales_representative=self.rep)
        self.private = Customer.objects.create(name='Private customer', sales_representative=self.other)
        self.client.force_login(self.rep)

    def test_statement_is_visible_read_only_and_scoped(self):
        url = reverse('finance:customer_statement')
        response = self.client.get(url, {'customer': self.customer.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['customer'], self.customer)
        self.assertIsNone(self.client.get(url, {'customer': self.private.pk}).context['customer'])
        self.assertEqual(self.client.post(url, {'customer': self.customer.pk}).status_code, 405)

    def test_other_business_routes_are_denied_for_both_get_and_post(self):
        urls = ['/returns/customer/create/', '/returns/simple/', '/finance/transactions/transfer/',
                '/customers/create/', f'/customers/{self.customer.pk}/update/',
                '/finance/transactions/collection/1/update/', '/products/create/',
                '/purchases/orders/create/', '/inventory/movements/in/', '/reports/']
        for url in urls:
            for method in ('get', 'post'):
                with self.subTest(url=url, method=method):
                    self.assertIn(getattr(self.client, method)(url).status_code, {403, 404})

    def test_required_offline_shell_routes_are_accessible(self):
        for url in ['/', '/orders/create/', '/orders/', '/finance/transactions/collection/',
                    '/finance/statements/customer/', '/products/representative/create/',
                    '/inventory/stock/', '/service-worker.js', '/manifest.json', '/offline/']:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_sample_cannot_be_submitted_through_sale_form(self):
        for document in ('sample',):
            self.assertEqual(self.client.get('/orders/create/', {'document': document}).status_code, 403)
            self.assertEqual(self.client.post('/orders/create/', {'document_type': document}).status_code, 403)

    def test_quote_screens_and_manifest_are_allowed_but_other_business_is_not(self):
        self.assertEqual(self.client.get('/orders/quotes/').status_code, 200)
        self.assertEqual(self.client.get('/orders/create/?document=quote').status_code, 200)
        payload = self.client.get('/api/sync/bootstrap-browser/').json()
        self.assertIn('/orders/create/?document=quote', payload['offline_pages'])
        self.assertNotIn('/purchases/orders/create/', payload['offline_pages'])
        self.assertNotIn(f'/customers/{self.private.pk}/', payload['offline_details'])

    def test_offline_quote_sync_is_idempotent_and_has_no_stock_or_cash_effect(self):
        from inventory.models import Warehouse, Stock
        from products.models import Product, ProductVariant
        from orders.models import Order
        warehouse = Warehouse.objects.create(name='Rep quote warehouse', assigned_user=self.rep, warehouse_type='representative')
        product = Product.objects.create(name='Quote product', sku='REP-QUOTE')
        variant = ProductVariant.objects.create(product=product, variant_sku='REP-QUOTE-V', retail_price=10, cost_price=5)
        stock = Stock.objects.create(warehouse=warehouse, variant=variant, quantity=5)
        operation = {'idempotency_key': 'offline-rep-quote', 'local_uuid': 'offline-rep-quote',
                     'device_id': 'rep-quote-device', 'entity_type': 'order', 'operation_type': 'create',
                     'payload': {'original_url': '/orders/create/',
                                 'order': {'document_type': 'quote', 'customer_server_id': self.customer.pk,
                                           'warehouse': warehouse.pk, 'action': 'confirm', 'payment_method': 'credit'},
                                 'items': [{'variant_id': variant.pk, 'warehouse_id': warehouse.pk,
                                            'quantity': 2, 'unit_price': '10'}]}}
        result = process_operation(operation, self.rep)
        self.assertEqual(result['status'], 'success', result)
        process_operation(operation, self.rep)
        self.assertEqual(Order.objects.filter(document_type='quote', created_by=self.rep).count(), 1)
        stock.refresh_from_db()
        self.assertEqual(stock.quantity, 5)
        self.assertEqual(CashAccount.objects.filter(balance__gt=0).count(), 0)

    def test_each_manifest_screen_is_accessible_for_its_role(self):
        from sync_api.offline_manifest import offline_pages
        for role in ('sales', 'manager', 'warehouse'):
            user = User.objects.create_user(username=f'offline-{role}', role=role)
            self.client.force_login(user)
            for url in offline_pages(user):
                with self.subTest(role=role, url=url):
                    self.assertEqual(self.client.get(url).status_code, 200)

    def test_bootstrap_downloads_only_visible_statements(self):
        payload = self.client.get('/api/sync/bootstrap-browser/').json()
        customers = {customer['id']: customer for customer in payload['customers']}
        self.assertIn('statement_snapshot', customers[self.customer.pk])
        self.assertNotIn(self.private.pk, customers)

    def test_online_collection_form_cannot_target_another_representatives_customer(self):
        from finance.forms import CustomerCollectionForm
        form = CustomerCollectionForm(user=self.rep)
        self.assertIn(self.customer, form.fields['customer'].queryset)
        self.assertNotIn(self.private, form.fields['customer'].queryset)

    def test_sync_rejects_forbidden_entities_and_financial_actions(self):
        account = CashAccount.objects.create(name='Rep cash', assigned_user=self.rep)
        cases = [
            ('customer', '/customers/create/', {}), ('return', '/returns/simple/', {}),
            ('payment', '/finance/transactions/transfer/', {'amount': '5'}),
            ('payment', '/finance/transactions/collection/', {'amount': '-5'}),
            ('payment', '/finance/transactions/collection/', {'amount': '5', 'allowed_discount': '2'}),
        ]
        for index, (entity, path, data) in enumerate(cases):
            result = process_operation({'idempotency_key': f'scope-{index}', 'device_id': 'scope-device',
                'local_uuid': f'scope-{index}', 'entity_type': entity, 'operation_type': 'create',
                'payload': {'original_url': path, entity: {**data, 'customer': self.customer.pk, 'cash_account': account.pk}}}, self.rep)
            self.assertEqual(result['status'], 'failed_conflict', result)
