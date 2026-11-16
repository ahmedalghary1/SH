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
                '/purchases/orders/create/', '/inventory/movements/in/', '/orders/quotes/', '/reports/']
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

    def test_quote_and_sample_cannot_be_submitted_through_sale_form(self):
        for document in ('quote', 'sample'):
            self.assertEqual(self.client.get('/orders/create/', {'document': document}).status_code, 403)
            self.assertEqual(self.client.post('/orders/create/', {'document_type': document}).status_code, 403)

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
