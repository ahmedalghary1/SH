import io
import os
import sqlite3
import tempfile
from pathlib import Path
from datetime import datetime
from unittest.mock import patch

from django import forms
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.http import HttpResponse, JsonResponse
from django.template.response import TemplateResponse
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import URLPattern, URLResolver, get_resolver, reverse
from django.utils import timezone
from openpyxl import load_workbook

from accounts.middleware import DuplicateSubmissionMiddleware
from accounts.models import Branch, SubmissionReceipt, User
from audit.services import log_audit
from config.branching import reset_current_branch, set_current_branch
from config.database import database_config
from config.date_ranges import resolve_date_period
from config.exports import export_csv_response, export_xlsx_response


class ConfigurationRegressionTests(SimpleTestCase):
    def test_legacy_database_file_does_not_use_linux_login_user(self):
        from config.settings import load_dotenv
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'USER': 'ssh-account'}, clear=True):
            env_file = Path(directory) / '.env'
            env_file.write_text('ENGINE=django.db.backends.postgresql\nNAME=existing_database\nUSER=database_role\nPASSWORD=private-test-only\nHOST=127.0.0.1\nPORT=5432\n', encoding='utf-8')
            load_dotenv(env_file)
            config = database_config(os.environ, directory)
            self.assertEqual(config['USER'], 'database_role')
            self.assertEqual(config['NAME'], 'existing_database')
            self.assertEqual(config['PASSWORD'], 'private-test-only')
            self.assertEqual(os.environ['USER'], 'ssh-account')

    def test_explicit_modern_process_database_values_override_legacy_file(self):
        from config.settings import load_dotenv
        process = {'USER': 'ssh-account', 'DB_ENGINE': 'postgres', 'POSTGRES_DB': 'current_database',
                   'POSTGRES_USER': 'current_role', 'POSTGRES_PASSWORD': 'current-test-only', 'DB_HOST': 'db.internal'}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, process, clear=True):
            env_file = Path(directory) / '.env'
            env_file.write_text('NAME=file_database\nUSER=file_role\nPASSWORD=file-test-only\nHOST=localhost\n', encoding='utf-8')
            load_dotenv(env_file)
            config = database_config(os.environ, directory)
            self.assertEqual(config['USER'], 'current_role')
            self.assertEqual(config['NAME'], 'current_database')
            self.assertEqual(config['PASSWORD'], 'current-test-only')
            self.assertEqual(config['HOST'], 'db.internal')

    def test_modern_file_database_values_override_legacy_file_aliases(self):
        from config.settings import load_dotenv
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'USER': 'ssh-account'}, clear=True):
            env_file = Path(directory) / '.env'
            env_file.write_text('DB_ENGINE=postgres\nNAME=legacy_database\nUSER=legacy_role\nPOSTGRES_DB=current_database\nPOSTGRES_USER=current_role\nPOSTGRES_PASSWORD=current-test-only\n', encoding='utf-8')
            load_dotenv(env_file)
            config = database_config(os.environ, directory)
            self.assertEqual(config['USER'], 'current_role')
            self.assertEqual(config['NAME'], 'current_database')

    def test_backup_includes_committed_wal_data(self):
        from config.management.commands.backup_db import Command
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / 'source.sqlite3'
            backup = Path(directory) / 'backup.sqlite3'
            source = sqlite3.connect(database)
            try:
                source.execute('PRAGMA journal_mode=WAL')
                source.execute('CREATE TABLE sample (value TEXT)')
                source.execute("INSERT INTO sample VALUES ('committed in WAL')")
                source.commit()
                config = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': str(database)}}
                with override_settings(DATABASES=config):
                    self.assertTrue(Command()._backup_sqlite(backup, None, backup))
                restored = sqlite3.connect(backup)
                try:
                    self.assertEqual(restored.execute('SELECT value FROM sample').fetchone()[0], 'committed in WAL')
                    self.assertEqual(restored.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                finally:
                    restored.close()
            finally:
                source.close()

    def test_failed_backup_verification_keeps_previous_backups(self):
        from config.management.commands.backup_db import Command
        command = Command()
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(command, '_backup_sqlite', return_value=True), patch.object(command, '_verify_backup', side_effect=SystemExit(1)), patch.object(command, '_rotate_backups') as rotate, override_settings(DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}):
                with self.assertRaises(SystemExit):
                    command.handle(keep=7, output=directory, verify=True, restore_test=False)
                rotate.assert_not_called()

    def test_server_error_renders_without_database_or_context_processors(self):
        from config.errors import server_error
        from config.middleware import RequestIdMiddleware
        response = RequestIdMiddleware(server_error)(RequestFactory().get('/orders/create/'))
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertContains(response, response['X-Request-ID'], status_code=500)

    def test_documented_sqlite_configuration_works(self):
        self.assertEqual(database_config({'DB_ENGINE': 'sqlite', 'SQLITE_PATH': ':memory:'}, '/tmp')['NAME'], ':memory:')

    def test_legacy_postgres_environment_and_health_checks(self):
        config = database_config({'ENGINE': 'django.db.backends.postgresql', 'NAME': 'erp', 'USER': 'erp_user', 'PASSWORD': 'private'}, '/tmp')
        self.assertEqual(config['NAME'], 'erp')
        self.assertEqual(config['PASSWORD'], 'private')
        self.assertTrue(config['CONN_HEALTH_CHECKS'])
        self.assertEqual(config['OPTIONS']['connect_timeout'], 10)

    def test_invalid_postgres_configuration_does_not_use_embedded_credentials(self):
        with self.assertRaises(ImproperlyConfigured):
            database_config({'DB_ENGINE': 'postgres'}, '/tmp')

    def test_calendar_invalid_values_do_not_crash_reports(self):
        selected = resolve_date_period({'period': 'custom', 'date_from': '2026-02-30', 'datetime_to': '2026-13-01T25:80'})
        self.assertIsNone(selected['date_from'])
        self.assertIsNone(selected['datetime_to'])

    def test_spreadsheet_exports_handle_timezones_and_plain_text(self):
        response = export_xlsx_response(filename='test', title='Report', headers=['Name', 'Time'], rows=[['=1+2', timezone.now()]])
        workbook = load_workbook(io.BytesIO(response.content))
        cell = workbook.active['A4']
        self.assertNotEqual(cell.data_type, 'f')
        self.assertIsInstance(workbook.active['B4'].value, datetime)
        csv = export_csv_response(filename='test', headers=['Name'], rows=[['=1+2']])
        self.assertIn("'=1+2", csv.content.decode('utf-8-sig'))


class WriteReliabilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(name='Test branch', code='RELIABILITY')
        cls.user = User.objects.create_user(username='reliability', branch=cls.branch, role='manager')

    def request(self, token='repeatable'):
        request = RequestFactory().post('/save/', {'_submission_token': token})
        request.user = self.user
        return request

    def test_duplicate_response_does_not_break_surrounding_transaction(self):
        middleware = DuplicateSubmissionMiddleware(lambda request: HttpResponse(status=302))
        self.assertEqual(middleware(self.request()).status_code, 302)
        self.assertEqual(middleware(self.request()).status_code, 409)
        self.assertEqual(SubmissionReceipt.objects.count(), 1)

    def test_failed_save_rolls_back_side_effects_and_allows_retry(self):
        def fail(request):
            Branch.objects.create(name='Rolled back', code='FAILED_WRITE')
            return HttpResponse(status=500)
        middleware = DuplicateSubmissionMiddleware(fail)
        self.assertEqual(middleware(self.request()).status_code, 500)
        self.assertFalse(Branch.objects.filter(code='FAILED_WRITE').exists())
        self.assertFalse(SubmissionReceipt.objects.exists())
        self.assertEqual(DuplicateSubmissionMiddleware(lambda request: HttpResponse(status=302))(self.request()).status_code, 302)

    def test_invalid_form_and_json_can_be_resubmitted(self):
        form = forms.Form({'amount': 'invalid'})
        form.fields['amount'] = forms.DecimalField()
        response = TemplateResponse(None, 'base.html', {'form': form})
        def invalid(request):
            Branch.objects.create(name='Invalid write', code='INVALID_WRITE')
            return response
        self.assertEqual(DuplicateSubmissionMiddleware(invalid)(self.request()).status_code, 200)
        self.assertFalse(Branch.objects.filter(code='INVALID_WRITE').exists())
        self.assertFalse(SubmissionReceipt.objects.exists())
        self.assertEqual(DuplicateSubmissionMiddleware(lambda request: JsonResponse({'success': False}))(self.request()).status_code, 200)
        self.assertFalse(SubmissionReceipt.objects.exists())

    def test_new_records_default_to_active_branch(self):
        from products.models import Category
        token = set_current_branch(self.branch.pk)
        try:
            category = Category.objects.create(name='Scoped category')
            self.assertEqual(category.branch_id, self.branch.pk)
        finally:
            reset_current_branch(token)

    def test_audit_ignores_malformed_ip_instead_of_failing_business_write(self):
        log_audit(user=self.user, action='update', section='accounts', ip_address='unknown proxy', branch=self.branch)
        self.assertIsNone(self.user.audit_logs.get().ip_address)

    def test_rate_limited_login_returns_recoverable_page(self):
        self.client.get(reverse('accounts:login'))
        with patch('accounts.views.rate_limit', side_effect=__import__('config.ratelimit', fromlist=['RateLimitExceeded']).RateLimitExceeded):
            response = self.client.post(reverse('accounts:login'), {'username': 'missing', 'password': 'invalid'})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response['Retry-After'], '60')
        cache.clear()


class PageSmokeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username='page-review', role='manager')

    def test_sales_user_cannot_confirm_cancel_or_return_another_users_order(self):
        from inventory.models import Warehouse
        from orders.models import Order
        warehouse = Warehouse.objects.create(name='Access-test warehouse')
        order = Order.objects.create(order_number='ACCESS-TEST', warehouse=warehouse, created_by=self.user)
        sales = User.objects.create_user(username='access-sales', role='sales')
        self.client.force_login(sales)
        for action in ('confirm', 'cancel', 'return'):
            self.assertEqual(self.client.post(reverse('orders:' + action, args=[order.pk])).status_code, 404)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_DRAFT)

    def test_malformed_invoice_lookup_ids_return_validation_errors(self):
        self.client.force_login(self.user)
        for parameter in ('warehouse_id', 'editing_order'):
            for value in ('invalid', '9' * 100, '-1'):
                response = self.client.get(reverse('orders:ajax_get_variant_stock', args=[1]), {parameter: value})
                self.assertEqual(response.status_code, 400)
        response = self.client.get(reverse('orders:ajax_get_variant_price', args=[1]), {'customer_id': 'invalid'})
        self.assertEqual(response.status_code, 400)

    def test_malformed_calculation_payloads_do_not_crash(self):
        from products.models import Product, ProductVariant
        product = Product.objects.create(name='Calculation product', sku='CALC-SAFE')
        variant = ProductVariant.objects.create(product=product, variant_sku='CALC-SAFE-V')
        self.client.force_login(self.user)
        payloads = [[], {'items': 'invalid'}, {'items': [None]},
                    {'paid_amount': 'NaN'}, {'paid_amount': '-1'},
                    {'customer_id': '9' * 100},
                    {'items': [{'variant_id': '9' * 100, 'quantity': 1}]},
                    {'items': [{'variant_id': variant.pk, 'quantity': 'NaN'}]}]
        for payload in payloads:
            with self.subTest(payload=payload):
                response = self.client.post(reverse('orders:ajax_calculate'), payload, content_type='application/json')
                self.assertEqual(response.status_code, 400)

    def test_application_get_routes_and_invalid_filters_never_return_500(self):
        self.client.force_login(self.user)

        def routes(patterns, prefix=''):
            for pattern in patterns:
                if isinstance(pattern, URLResolver):
                    if str(pattern.pattern) != 'admin/':
                        yield from routes(pattern.url_patterns, prefix + str(pattern.pattern))
                elif isinstance(pattern, URLPattern):
                    route = prefix + str(pattern.pattern)
                    # Exercise actual application paths, excluding wildcard file serving.
                    if '(?P<' in route:
                        continue
                    import re
                    route = re.sub(r'<(?:int:)?[^>]+>', '1', route)
                    yield '/' + route

        client = Client(raise_request_exception=False)
        client.force_login(self.user)
        for path in sorted(set(routes(get_resolver().url_patterns))):
            for filters in ({}, {'date_from': '2026-02-30', 'datetime_to': '2026-13-01T25:80', 'days': 'invalid', 'customer': 'invalid', 'warehouse': 'invalid'}):
                with self.subTest(path=path, filters=filters):
                    response = client.get(path, filters)
                    self.assertLess(response.status_code, 500)
                    if response.streaming:
                        # The test client's streaming iterator closes resources
                        # without closing the surrounding PostgreSQL transaction.
                        b''.join(response.streaming_content)
