from base64 import b64decode
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from io import BytesIO
from io import StringIO
import errno
import hashlib
import json
import logging
from pathlib import Path
import tempfile
import smtplib
import stat
import threading
from unittest.mock import patch
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core import mail
from django.core.management import call_command
from django.db import DatabaseError, connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone

from accounts.models import Branch, User
from audit.models import AuditLog
from config import error_email
from config.log_sanitizer import SanitizingFilter
from config.branching import reset_current_branch, set_current_branch
from customers.models import Customer
from finance.models import CashAccount, PaymentTransaction
from finance.services import collect_order_payment
from inventory.models import Stock, StockBatch, Warehouse
from inventory.services import stock_in
from invoices.models import Invoice
from invoices.services import delete_invoice, generate_invoice
from orders.models import Order
from orders.services import create_order
from products.models import Category, Product, ProductVariant
from returns.models import SalesReturn
from returns.services import add_return_item, approve_sales_return, cancel_sales_return, complete_sales_return, create_sales_return
from sync_api.models import SyncOperation

from . import backup_services as backups
from . import backup_replace as replacement
from .backup_resolution import KEEP_CURRENT, USE_ARCHIVE
from .models import BackupIdentity, BackupImport, CompanySettings


PNG = b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jB1sAAAAASUVORK5CYII=')


class CompleteBackupTests(TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='sh-backup-tests-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.media = self.root / 'destination-media'
        self.media.mkdir()
        self.override = override_settings(
            MEDIA_ROOT=self.media, MEDIA_FALLBACK_ROOTS=[],
            BACKUP_PRIVATE_ROOT=self.root / 'private',
            PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
        )
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.admin = User.objects.create_superuser(username='backup-admin', password='test-secret')
        request_logger = logging.getLogger('django.request')
        was_disabled = request_logger.disabled
        request_logger.disabled = True
        self.addCleanup(setattr, request_logger, 'disabled', was_disabled)

    def upload(self, data, name='backup.zip'):
        return SimpleUploadedFile(name, data, content_type='application/zip')

    def make_source(self, later=False):
        source_media = self.root / 'source-media'
        source_media.mkdir(exist_ok=True)
        (source_media / 'products').mkdir(exist_ok=True)
        (source_media / 'products/item.png').write_bytes(PNG)
        (source_media / 'unused.txt').write_text('A detached attachment', encoding='utf-8')
        with transaction.atomic():
            branch = Branch.objects.create(code='SOURCE', name='Source branch')
            token = set_current_branch(branch.pk)
            try:
                manager = User.objects.create_user(username='source-manager', password='source-pass',
                                                   role='manager', branch=branch)
                warehouse = Warehouse.objects.create(name='Source warehouse', warehouse_type='main')
                customer = Customer.objects.create(name='Source customer', created_by=manager)
                product = Product.objects.create(name='Source product', sku='SOURCE-P', image='products/item.png')
                variant = ProductVariant.objects.create(product=product, variant_sku='SOURCE-V',
                                                         cost_price=5, retail_price=10, sale_price=10)
                stock_in(variant=variant, warehouse=warehouse, quantity=20, unit_cost=5, user=manager)
                order = create_order(order_data={'customer': customer, 'warehouse': warehouse,
                                                 'order_type': Order.TYPE_B2C, 'payment_method': Order.METHOD_CREDIT},
                                     items=[{'variant': variant, 'warehouse': warehouse, 'quantity': 4, 'unit_price': 10}],
                                     user=manager, confirm=True)
                generate_invoice(order, user=manager)
                cash = CashAccount.get_default()
                collect_order_payment(order=order, amount=Decimal('20'), cash_account=cash, user=manager)
                returned = create_sales_return(order=order, return_type=SalesReturn.TYPE_PARTIAL_RETURN, user=manager)
                add_return_item(sales_return=returned, original_order_item=order.items.get(), quantity=1,
                                condition='good', return_to_stock=True)
                approve_sales_return(sales_return=returned, user=manager)
                complete_sales_return(sales_return=returned, user=manager, cash_account=cash)
                SyncOperation.objects.create(
                    idempotency_key='backup-source-product-key', user=manager, device_id='source-device',
                    entity_type='products', operation_type='create', local_uuid='local-product',
                    server_model='Product', server_object_id=str(product.pk),
                    response_json={'status': 'success', 'server_id': product.pk, 'server_model': 'Product',
                                   'variant_id': variant.pk},
                )
                with override_settings(MEDIA_ROOT=source_media):
                    with backups.build_backup() as stream:
                        original = stream.read()
                    newer = None
                    if later:
                        stock_in(variant=variant, warehouse=warehouse, quantity=5, unit_cost=6, user=manager)
                        collect_order_payment(order=Order.objects.get(pk=order.pk),
                                              amount=Decimal('10'), cash_account=cash, user=manager)
                        Product.objects.create(name='New catalog product', sku='SOURCE-NEW')
                        with backups.build_backup() as stream:
                            newer = stream.read()
                transaction.set_rollback(True)
                return original, newer
            finally:
                reset_current_branch(token)

    def import_data(self, data):
        job = backups.stage_upload(self.upload(data), self.admin)
        self.assertEqual(job.summary['conflict_count'], 0, job.summary['conflicts'])
        return backups.apply_import(job.pk, self.admin)

    def test_full_round_trip_preserves_balances_relations_images_and_sync_ids(self):
        data, _ = self.make_source()
        # Occupy source-like primary keys with unrelated destination records.
        target = Branch.objects.create(code='TARGET', name='Existing branch')
        Product.objects.create(branch=target, name='Existing product', sku='KEEP')
        user_password = self.admin.password
        self.import_data(data)
        source = Branch.objects.get(code='SOURCE')
        product = Product.all_objects.get(sku='SOURCE-P')
        variant = ProductVariant.all_objects.get(product=product)
        order = Order.all_objects.get(branch=source)
        self.assertEqual(Stock.all_objects.get(branch=source).quantity, 17)
        self.assertEqual(sum(StockBatch.all_objects.filter(branch=source).values_list('remaining_quantity', flat=True)), 17)
        self.assertEqual(CashAccount.all_objects.get(branch=source).balance, Decimal('20.00'))
        self.assertEqual(order.paid_amount, Decimal('20.00'))
        self.assertEqual(order.remaining_amount, Decimal('10.00'))
        self.assertEqual(order.items.get().variant_id, variant.pk)
        self.assertEqual(Invoice.all_objects.get(order=order).order_id, order.pk)
        self.assertEqual(SalesReturn.all_objects.get(order=order).items.get().original_order_item_id, order.items.get().pk)
        self.assertEqual((self.media / str(product.image)).read_bytes(), PNG)
        self.assertFalse((self.media / 'unused.txt').exists())
        self.assertTrue(Product.all_objects.filter(sku='KEEP').exists())
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.password, user_password)
        sync = SyncOperation.all_objects.get(idempotency_key='backup-source-product-key')
        self.assertEqual(sync.server_object_id, str(product.pk))
        self.assertEqual(sync.response_json['server_id'], product.pk)
        self.assertEqual(sync.response_json['variant_id'], variant.pk)
        manager = User.all_objects.get(username='source-manager')
        self.assertTrue(manager.check_password('source-pass'))

    def test_repeated_archive_and_repeated_confirmation_do_not_duplicate(self):
        data, _ = self.make_source()
        first = self.import_data(data)
        before = (Order.all_objects.count(), PaymentTransaction.all_objects.count(), StockBatch.all_objects.count())
        backups.apply_import(first.pk, self.admin)
        second = self.import_data(data)
        self.assertEqual(second.summary['create'], 0)
        self.assertEqual(second.summary['update'], 0)
        self.assertEqual(second.summary['media_new'], 0)
        self.assertEqual(before, (Order.all_objects.count(), PaymentTransaction.all_objects.count(), StockBatch.all_objects.count()))
        self.assertEqual(CashAccount.all_objects.get(branch__code='SOURCE').balance, Decimal('20'))

    def test_repeated_archive_accepts_same_timestamp_with_zero_fraction(self):
        with transaction.atomic():
            product = Product.objects.create(name='Legacy timestamp', sku='BACKUP-TIMESTAMP')
            Product.objects.filter(pk=product.pk).update(created_at=timezone.now().replace(microsecond=1))
            with backups.build_backup() as stream:
                data = stream.read()
            transaction.set_rollback(True)

        self.import_data(data)
        self.assertEqual(Product.objects.get(sku='BACKUP-TIMESTAMP').created_at.microsecond, 0)
        again = self.import_data(data)
        self.assertEqual(again.summary['create'], 0)
        self.assertEqual(again.summary['update'], 0)

    def test_restored_return_and_invoice_can_be_cancelled_with_correct_cash_and_stock(self):
        data, _ = self.make_source()
        self.import_data(data)
        manager = User.all_objects.get(username='source-manager')
        returned = SalesReturn.all_objects.get(branch__code='SOURCE')
        token = set_current_branch(manager.branch_id)
        try:
            cancel_sales_return(sales_return=returned, user=manager, reason='Restore integration test')
            invoice = Invoice.all_objects.get(branch__code='SOURCE')
            delete_invoice(invoice=invoice, user=manager)
        finally:
            reset_current_branch(token)
        self.assertEqual(Stock.all_objects.get(branch__code='SOURCE').quantity, 20)
        self.assertEqual(CashAccount.all_objects.get(branch__code='SOURCE').balance, Decimal('0'))
        self.assertEqual(Order.all_objects.get(branch__code='SOURCE').remaining_amount, Decimal('0'))

    def test_self_referencing_catalog_is_restored_without_disabling_constraints(self):
        with transaction.atomic():
            category = Category.objects.create(name='Self category')
            Category.objects.filter(pk=category.pk).update(parent_id=category.pk)
            with backups.build_backup() as stream:
                data = stream.read()
            transaction.set_rollback(True)
        self.import_data(data)
        restored = Category.all_objects.get(name='Self category')
        self.assertEqual(restored.parent_id, restored.pk)

    def test_old_catalog_identity_can_alias_a_recreated_record_without_replacing_it(self):
        product = Product.objects.create(name='Original', sku='RECREATED')
        with backups.build_backup() as stream:
            original = stream.read()
        product.delete()
        current = Product.objects.create(name='Current version', sku='RECREATED')
        with backups.build_backup():
            pass
        result = self.import_data(original)
        current.refresh_from_db()
        self.assertEqual(current.name, 'Current version')
        self.assertEqual(result.summary['create'], 0)
        self.assertEqual(BackupIdentity.objects.filter(model_label='products.product',
                                                      object_pk=str(current.pk), is_primary=True).count(), 1)

    def test_legacy_company_settings_rows_restore_separately_in_their_branch(self):
        branch = Branch.objects.create(code='LEGACY-SETTINGS', name='Legacy settings')
        current = CompanySettings.objects.create(branch=branch, company_name='Active settings')
        with transaction.atomic():
            CompanySettings.objects.create(branch=branch, company_name='Legacy settings 1')
            CompanySettings.objects.create(branch=branch, company_name='Legacy settings 2')
            with backups.build_backup() as stream:
                data = stream.read()
            transaction.set_rollback(True)

        def reverse_record_order(files):
            records = json.loads(files['data.json'])
            files['data.json'] = backups.canonical(records[::-1])
            manifest = json.loads(files['manifest.json'])
            manifest['data_sha256'] = hashlib.sha256(files['data.json']).hexdigest()
            files['manifest.json'] = backups.canonical(manifest)

        data = self.rewrite(data, change=reverse_record_order)
        result = self.import_data(data)
        settings_rows = CompanySettings.all_objects.filter(branch=branch).order_by('pk')
        self.assertEqual(list(settings_rows.values_list('company_name', flat=True)),
                         ['Active settings', 'Legacy settings 1', 'Legacy settings 2'])
        self.assertEqual(settings_rows.first().pk, current.pk)
        self.assertEqual(result.summary['create'], 2)
        self.assertEqual(self.import_data(data).summary['create'], 0)
        self.assertEqual(settings_rows.count(), 3)

    def test_distinct_business_identities_cannot_merge_into_the_same_target(self):
        first = Product.objects.create(name='First product', sku='BACKUP-IDENTITY-1')
        second = Product.objects.create(name='Second product', sku='BACKUP-IDENTITY-2')
        with backups.build_backup() as stream:
            data = stream.read()
        BackupIdentity.objects.filter(model_label='products.product', object_pk=str(second.pk)).update(
            object_pk=str(first.pk), is_primary=False,
        )

        with self.assertRaisesMessage(backups.BackupError, 'يطابقان السجل الحالي'):
            backups.stage_upload(self.upload(data), self.admin)
        self.assertEqual(Product.objects.get(pk=first.pk).sku, 'BACKUP-IDENTITY-1')
        self.assertEqual(Product.objects.get(pk=second.pk).sku, 'BACKUP-IDENTITY-2')

    def test_newer_descendant_snapshot_updates_balances_once(self):
        old, new = self.make_source(later=True)
        self.import_data(old)
        newer = self.import_data(new)
        self.assertGreater(newer.summary['update'], 0)
        self.assertEqual(Stock.all_objects.get(branch__code='SOURCE').quantity, 22)
        self.assertEqual(CashAccount.all_objects.get(branch__code='SOURCE').balance, Decimal('30'))
        self.assertEqual(Order.all_objects.get(branch__code='SOURCE').remaining_amount, Decimal('0'))
        self.import_data(new)
        self.import_data(old)
        self.assertEqual(Stock.all_objects.get(branch__code='SOURCE').quantity, 22)
        self.assertEqual(CashAccount.all_objects.get(branch__code='SOURCE').balance, Decimal('30'))

    def test_divergent_balance_blocks_entire_merge(self):
        old, new = self.make_source(later=True)
        self.import_data(old)
        cash = CashAccount.all_objects.get(branch__code='SOURCE')
        CashAccount.all_objects.filter(pk=cash.pk).update(balance=Decimal('999'))
        before = PaymentTransaction.all_objects.count()
        job = backups.stage_upload(self.upload(new), self.admin)
        self.assertGreater(job.summary['conflict_count'], 0)
        with self.assertRaises(backups.BackupError):
            backups.apply_import(job.pk, self.admin)
        cash.refresh_from_db()
        self.assertEqual(cash.balance, Decimal('999'))
        self.assertEqual(before, PaymentTransaction.all_objects.count())
        self.assertEqual(Stock.all_objects.get(branch__code='SOURCE').quantity, 17)

    def test_keep_current_applies_independent_creates_and_holds_conflicting_ledger(self):
        old, new = self.make_source(later=True)
        self.import_data(old)
        cash = CashAccount.all_objects.get(branch__code='SOURCE')
        CashAccount.all_objects.filter(pk=cash.pk).update(balance=Decimal('999'))
        before = PaymentTransaction.all_objects.count()
        job = backups.stage_upload(self.upload(new), self.admin)
        self.client.force_login(self.admin)
        url = reverse('settings_app:backup_preview', kwargs={'job_id': job.pk})
        response = self.client.post(url, {'preview_resolution': '1', 'resolution': KEEP_CURRENT}, follow=True)
        self.assertContains(response, 'معاينة الاختيار')
        self.assertContains(response, 'تأكيد دمج البيانات والصور')
        self.assertContains(response, '999.00')
        self.assertFalse(Product.all_objects.filter(sku='SOURCE-NEW').exists())
        with self.assertRaisesMessage(backups.BackupError, 'تغير خيار'):
            backups.apply_import(job.pk, self.admin, resolution=USE_ARCHIVE)
        response = self.client.post(url, {'confirm': 'on', 'resolution': KEEP_CURRENT}, follow=True)
        self.assertContains(response, 'اكتمل دمج النسخة')
        self.assertTrue(Product.all_objects.filter(sku='SOURCE-NEW').exists())
        cash.refresh_from_db()
        self.assertEqual(cash.balance, Decimal('999'))
        self.assertEqual(PaymentTransaction.all_objects.count(), before)
        self.assertEqual(Stock.all_objects.get(branch__code='SOURCE').quantity, 17)
        job.refresh_from_db()
        self.assertGreater(job.summary['deferred_count'], 0)

    def test_use_archive_applies_complete_ledger_and_uses_archived_values(self):
        old, new = self.make_source(later=True)
        self.import_data(old)
        cash = CashAccount.all_objects.get(branch__code='SOURCE')
        CashAccount.all_objects.filter(pk=cash.pk).update(balance=Decimal('999'))
        Product.all_objects.filter(sku='SOURCE-P').update(name='Local catalog name')
        job = backups.stage_upload(self.upload(new), self.admin)
        preview = backups.preview_resolution(job.pk, self.admin, USE_ARCHIVE)
        self.assertGreater(preview.summary['update'], 0)
        self.assertEqual(preview.summary['deferred_count'], 0)
        backups.apply_import(job.pk, self.admin, resolution=USE_ARCHIVE)
        cash.refresh_from_db()
        self.assertEqual(cash.balance, Decimal('30'))
        self.assertEqual(Stock.all_objects.get(branch__code='SOURCE').quantity, 22)
        self.assertEqual(Order.all_objects.get(branch__code='SOURCE').remaining_amount, Decimal('0'))
        self.assertEqual(Product.all_objects.get(sku='SOURCE-P').name, 'Source product')
        self.assertEqual(self.import_data(new).summary['update'], 0)

    def test_use_archive_holds_ledger_with_local_only_movements(self):
        old, new = self.make_source(later=True)
        self.import_data(old)
        manager = User.objects.get(username='source-manager')
        variant = ProductVariant.all_objects.get(branch_id=manager.branch_id)
        warehouse = Warehouse.all_objects.get(branch_id=manager.branch_id)
        token = set_current_branch(manager.branch_id)
        try:
            stock_in(variant=variant, warehouse=warehouse, quantity=7, unit_cost=6, user=manager)
        finally:
            reset_current_branch(token)
        job = backups.stage_upload(self.upload(new), self.admin)
        preview = backups.preview_resolution(job.pk, self.admin, USE_ARCHIVE)
        self.assertGreater(preview.summary['deferred_count'], 0)
        backups.apply_import(job.pk, self.admin, resolution=USE_ARCHIVE)
        self.assertEqual(Stock.all_objects.get(branch_id=manager.branch_id).quantity, 24)
        self.assertEqual(CashAccount.all_objects.get(branch_id=manager.branch_id).balance, Decimal('20'))
        self.assertTrue(Product.all_objects.filter(sku='SOURCE-NEW').exists())

    def test_changed_data_after_preview_requires_fresh_preview(self):
        data, _ = self.make_source()
        job = backups.stage_upload(self.upload(data), self.admin)
        Customer.objects.create(name='Created after preview')
        with self.assertRaisesMessage(backups.BackupError, 'بعد المعاينة'):
            backups.apply_import(job.pk, self.admin)
        self.assertFalse(Product.all_objects.filter(sku='SOURCE-P').exists())
        self.assertFalse((self.media / 'products/item.png').exists())

    def test_media_collision_keeps_existing_bytes_and_rewrites_product_path(self):
        data, _ = self.make_source()
        (self.media / 'products').mkdir()
        (self.media / 'products/item.png').write_bytes(b'existing-image-bytes')
        result = self.import_data(data)
        product = Product.all_objects.get(sku='SOURCE-P')
        self.assertEqual(result.summary['media_renamed'], 1)
        self.assertTrue(str(product.image).startswith('restored/'))
        self.assertEqual((self.media / str(product.image)).read_bytes(), PNG)
        self.assertEqual((self.media / 'products/item.png').read_bytes(), b'existing-image-bytes')
        again = self.import_data(data)
        self.assertEqual(again.summary['conflict_count'], 0)

    def test_filesystem_failure_rolls_back_database_and_new_files(self):
        data, _ = self.make_source()
        job = backups.stage_upload(self.upload(data), self.admin)
        install = backups._install_media

        def fail_after_install(*args):
            install(*args)
            raise OSError('disk failure')

        with patch.object(backups, '_install_media', side_effect=fail_after_install):
            with self.assertRaises(OSError):
                backups.apply_import(job.pk, self.admin)
        self.assertFalse(Branch.objects.filter(code='SOURCE').exists())
        self.assertFalse(Product.all_objects.filter(sku='SOURCE-P').exists())
        self.assertFalse(any(p.is_file() for p in self.media.rglob('*')))
        job.refresh_from_db()
        self.assertIsNone(job.completed_at)
        self.assertTrue(backups.staged_path(job.pk).exists())

    def rewrite(self, data, change=None, extra=None):
        output = BytesIO()
        with zipfile.ZipFile(BytesIO(data)) as source, zipfile.ZipFile(output, 'w') as target:
            files = {name: source.read(name) for name in source.namelist()}
            if change:
                change(files)
            if extra:
                files.update(extra)
            for name, contents in files.items():
                target.writestr(name, contents)
        return output.getvalue()

    def test_zip_traversal_symlink_and_unlisted_files_are_rejected(self):
        data, _ = self.make_source()
        for name in ['../escape.txt', '/absolute.txt', 'media/../../escape.txt', 'media/CON.png', 'unknown.txt']:
            with self.subTest(name=name), self.assertRaises(backups.BackupError):
                backups.stage_upload(self.upload(self.rewrite(data, extra={name: b'bad'})), self.admin)
        self.assertFalse((self.root / 'escape.txt').exists())
        self.assertEqual(BackupImport.objects.count(), 0)

    def test_corrupt_media_and_data_checksums_are_rejected(self):
        data, _ = self.make_source()
        for path in ['data.json', 'media/products/item.png']:
            with self.subTest(path=path), self.assertRaises(backups.BackupError):
                backups.stage_upload(self.upload(self.rewrite(data, extra={path: b'changed'})), self.admin)

    def test_archive_limits_are_enforced_before_extraction(self):
        data, _ = self.make_source()
        with override_settings(BACKUP_MAX_UPLOAD_BYTES=10), self.assertRaises(backups.BackupError):
            backups.stage_upload(self.upload(data), self.admin)
        with override_settings(BACKUP_MAX_EXPANDED_BYTES=10), self.assertRaises(backups.BackupError):
            backups.stage_upload(self.upload(data), self.admin)

    def test_backup_contains_fallback_media_and_reports_missing_images(self):
        fallback = self.root / 'fallback'
        fallback.mkdir()
        (fallback / 'legacy.png').write_bytes(PNG)
        Product.objects.create(name='Legacy SH image', sku='LEGACY-SH', image='legacy.png')
        Product.objects.create(name='Missing image', sku='MISSING', image='not-there.png')
        with override_settings(MEDIA_FALLBACK_ROOTS=[fallback]), backups.build_backup() as stream:
            with zipfile.ZipFile(stream) as archive:
                manifest = json.loads(archive.read('manifest.json'))
                self.assertEqual(archive.read('media/legacy.png'), PNG)
                self.assertIn('not-there.png', manifest['missing_media'])
                self.assertNotIn('sessions.session', manifest['counts'])
                self.assertNotIn('.env', archive.namelist())

    def test_json_path_key_is_not_treated_as_a_file_field(self):
        value = {'path': '/orders/42/', 'message': 'ordinary audit JSON'}
        log = AuditLog.objects.create(user=self.admin, action='update', section='settings',
                                      changes_after=value)
        with backups.build_backup() as stream:
            manifest, records = backups.read_archive(stream)
        record = next(r for r in records if r['model'] == 'audit.auditlog' and r['source_pk'] == str(log.pk))
        self.assertEqual(record['fields']['changes_after'], value)
        self.assertNotIn('/orders/42/', manifest['missing_media'])

    def test_unreadable_referenced_media_fails_instead_of_omitting_attachments(self):
        (self.media / 'products').mkdir()
        image = self.media / 'products/item.png'
        image.write_bytes(PNG)
        original = Path.lstat

        def unreadable(path, *args, **kwargs):
            if path == image:
                raise PermissionError(errno.EACCES, 'unreadable SH attachment')
            return original(path, *args, **kwargs)

        with patch.object(Path, 'lstat', unreadable):
            with self.assertRaises(PermissionError):
                backups.media_inventory(['products/item.png'])

    def test_shared_server_exports_only_sh_file_field_references_without_scanning(self):
        shared = self.root / 'public_html'
        legacy = shared / 'media'
        assets = {
            'sh_media/products/sh.png': PNG,
            'media/product_variants/sh.png': b'SH legacy variant',
            'media/brand/sh-logo.png': b'SH logo',
            'media/products/other-site.png': b'Other site catalog',
            'media/site-two/banner.jpg': b'Other site banner',
            'site-three/uploads/photo.png': b'Third site image',
            'sh_media/unlinked.png': b'Unproven ownership',
            '.env': b'Unrelated private configuration',
        }
        for name, content in assets.items():
            target = shared / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        product = Product.objects.create(name='SH product', sku='SH-ONLY', image='products/sh.png')
        ProductVariant.objects.create(product=product, variant_sku='SH-ONLY-V', image='product_variants/sh.png')
        CompanySettings.objects.create(logo='brand/sh-logo.png')
        AuditLog.objects.create(user=self.admin, action='update', section='settings',
                                changes_after={'path': 'site-two/banner.jpg'})
        with override_settings(MEDIA_ROOT=shared / 'sh_media', MEDIA_FALLBACK_ROOTS=[legacy, shared]), \
                patch('os.walk', side_effect=AssertionError('Must not scan hosted sites')), \
                patch.object(backups, 'file_digest', wraps=backups.file_digest) as hashed:
            with backups.build_backup() as stream, zipfile.ZipFile(stream) as archive:
                manifest = json.loads(archive.read('manifest.json'))
                self.assertEqual(set(archive.namelist()), {
                    'manifest.json', 'data.json', 'media/products/sh.png',
                    'media/product_variants/sh.png', 'media/brand/sh-logo.png',
                })
                self.assertEqual(archive.read('media/products/sh.png'), PNG)
                self.assertEqual(manifest['missing_media'], [])
            self.assertEqual({call.args[0] for call in hashed.call_args_list}, {
                shared / 'sh_media/products/sh.png', legacy / 'product_variants/sh.png', legacy / 'brand/sh-logo.png',
            })
        self.assertEqual((legacy / 'site-two/banner.jpg').read_bytes(), b'Other site banner')

    def test_shared_primary_media_root_does_not_export_unrelated_files(self):
        (self.media / 'sh.png').write_bytes(PNG)
        (self.media / 'other-site').mkdir()
        (self.media / 'other-site/private.png').write_bytes(b'Other site')
        Product.objects.create(name='SH shared root', sku='SH-SHARED', image='sh.png')
        with backups.build_backup() as stream, zipfile.ZipFile(stream) as archive:
            self.assertEqual(set(archive.namelist()), {'manifest.json', 'data.json', 'media/sh.png'})

    def test_legacy_archive_unlinked_attachment_still_restores_without_reexporting_it(self):
        data, _ = self.make_source()
        content = b'Attachment included by an older SH release'

        def legacy_attachment(files):
            manifest = json.loads(files['manifest.json'])
            manifest['media'].append({'path': 'legacy-unlinked.txt', 'size': len(content),
                                      'sha256': hashlib.sha256(content).hexdigest()})
            files['manifest.json'] = backups.canonical(manifest)
            files['media/legacy-unlinked.txt'] = content

        legacy = self.rewrite(data, change=legacy_attachment)
        self.import_data(legacy)
        self.assertEqual((self.media / 'legacy-unlinked.txt').read_bytes(), content)
        with backups.build_backup() as stream, zipfile.ZipFile(stream) as archive:
            self.assertNotIn('media/legacy-unlinked.txt', archive.namelist())

    def test_unsafe_database_file_reference_cannot_read_a_sibling_site(self):
        Product.objects.create(name='Invalid media path', sku='SH-UNSAFE', image='../other-site/private.png')
        with self.assertRaises(backups.BackupError), patch.object(backups, 'file_digest') as hashed:
            backups.build_backup()
        hashed.assert_not_called()

    def test_media_priority_keeps_primary_sh_image_when_fallback_has_same_name(self):
        fallback = self.root / 'shared-media'
        fallback.mkdir()
        (self.media / 'same.png').write_bytes(PNG)
        (fallback / 'same.png').write_bytes(b'Different site image')
        Product.objects.create(name='Primary image', sku='SH-PRIORITY', image='same.png')
        with override_settings(MEDIA_FALLBACK_ROOTS=[fallback]):
            with backups.build_backup() as stream, zipfile.ZipFile(stream) as archive:
                self.assertEqual(archive.read('media/same.png'), PNG)

    def test_referenced_symlink_component_is_rejected_before_reading_it(self):
        linked = self.media / 'linked'
        linked.mkdir()
        original = Path.lstat

        def symbolic(path, *args, **kwargs):
            if path == linked:
                return type('LinkInfo', (), {'st_mode': stat.S_IFLNK})()
            return original(path, *args, **kwargs)

        with patch.object(Path, 'lstat', symbolic), self.assertRaisesMessage(backups.BackupError, 'رابط رمزي'):
            backups.media_inventory(['linked/other-site.png'])

    def test_import_preserves_unreferenced_directory_at_an_incoming_image_path(self):
        data, _ = self.make_source()
        directory = self.media / 'products/item.png'
        directory.mkdir(parents=True)
        (directory / 'other-site.txt').write_bytes(b'Keep directory contents')
        result = self.import_data(data)
        self.assertEqual(result.summary['media_renamed'], 1)
        product = Product.all_objects.get(sku='SOURCE-P')
        self.assertEqual((self.media / str(product.image)).read_bytes(), PNG)
        self.assertEqual((directory / 'other-site.txt').read_bytes(), b'Keep directory contents')

    def test_import_preserves_unreferenced_file_blocking_an_incoming_directory(self):
        data, _ = self.make_source()
        (self.media / 'products').write_bytes(b'Keep ancestor file')
        result = self.import_data(data)
        self.assertEqual(result.summary['media_renamed'], 1)
        product = Product.all_objects.get(sku='SOURCE-P')
        self.assertEqual((self.media / str(product.image)).read_bytes(), PNG)
        self.assertEqual((self.media / 'products').read_bytes(), b'Keep ancestor file')

    def test_changed_unreferenced_destination_after_preview_requires_fresh_preview(self):
        data, _ = self.make_source()
        (self.media / 'products').mkdir()
        image = self.media / 'products/item.png'
        image.write_bytes(b'Unrelated existing file')
        job = backups.stage_upload(self.upload(data), self.admin)
        image.write_bytes(b'Changed after preview')
        with self.assertRaisesMessage(backups.BackupError, 'بعد المعاينة'):
            backups.apply_import(job.pk, self.admin)
        self.assertEqual(image.read_bytes(), b'Changed after preview')

    def test_records_limit_is_checked_before_creating_identities(self):
        with override_settings(BACKUP_MAX_RECORDS=1):
            with self.assertRaises(backups.BackupError), patch.object(backups, '_global_uid') as assign:
                backups.collect_snapshot()
        assign.assert_not_called()

    def test_diagnostic_command_builds_and_validates_without_importing(self):
        output = StringIO()
        count = Order.all_objects.count()
        call_command('check_backups', create=True, stdout=output)
        self.assertIn('ZIP verified:', output.getvalue())
        self.assertEqual(Order.all_objects.count(), count)
        self.assertEqual(BackupImport.objects.count(), 0)

    def test_expired_preview_and_other_owner_cannot_apply(self):
        data, _ = self.make_source()
        job = backups.stage_upload(self.upload(data), self.admin)
        BackupImport.objects.filter(pk=job.pk).update(created_at=timezone.now() - timedelta(hours=2))
        with self.assertRaises(backups.BackupError):
            backups.apply_import(job.pk, self.admin)
        backups.cleanup_archives()
        self.assertFalse(backups.staged_path(job.pk).exists())

    def test_non_superusers_cannot_download_preview_or_apply(self):
        data, _ = self.make_source()
        job = backups.stage_upload(self.upload(data), self.admin)
        for role in ['manager', 'director', 'sales', 'warehouse']:
            user = User.objects.create_user(username=f'user-{role}', role=role)
            self.client.force_login(user)
            for name, kwargs in [('backups', {}), ('backup_download', {}), ('backup_preview', {'job_id': job.pk})]:
                with self.subTest(role=role, name=name):
                    url = reverse('settings_app:' + name, kwargs=kwargs)
                    self.assertEqual(self.client.get(url).status_code, 403)
                    self.assertEqual(self.client.post(url, {'confirm': True}).status_code, 403)

    def test_web_download_and_two_step_confirmation(self):
        data, _ = self.make_source()
        self.client.force_login(self.admin)
        download = self.client.get(reverse('settings_app:backup_download'))
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download['Content-Type'], 'application/zip')
        self.assertIn('no-store', download['Cache-Control'])
        self.assertNotIn('X-PWA-Cacheable', download)
        raw = b''.join(download.streaming_content)
        self.assertEqual(int(download['Content-Length']), len(raw))
        self.assertTrue(raw.startswith(b'PK'))
        self.assertTrue(zipfile.is_zipfile(BytesIO(raw)))
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            self.assertIsNone(archive.testzip())
        response = self.client.post(reverse('settings_app:backups'), {'archive': self.upload(data)})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Product.all_objects.filter(sku='SOURCE-P').exists())
        url = response['Location']
        preview = self.client.get(url)
        self.assertContains(preview, 'احفظ نسخة أمان أولًا')
        self.assertNotIn('X-PWA-Cacheable', preview)
        unchecked = self.client.post(url)
        self.assertEqual(unchecked.status_code, 200)
        self.assertFalse(Product.all_objects.filter(sku='SOURCE-P').exists())
        self.assertEqual(self.client.post(url, {'confirm': 'on'}).status_code, 200)
        self.assertFalse(Product.all_objects.filter(sku='SOURCE-P').exists())
        applied = self.client.post(url, {'confirm': 'on', 'saved_backup': 'on'})
        self.assertContains(applied, 'اكتملت استعادة النسخة')
        self.assertTrue(Product.all_objects.filter(sku='SOURCE-P').exists())
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(self.client.post(url, {'confirm': 'on', 'saved_backup': 'on'}).status_code, 302)

    def test_full_replacement_restores_archived_data_and_saves_previous_state(self):
        data, _ = self.make_source()
        old_branch = Branch.objects.create(code='LOCAL-ONLY', name='Current branch')
        old_product = Product.objects.create(branch=old_branch, sku='LOCAL-ONLY', name='Current product')
        local_user = User.objects.create_user(username='local-only', branch=old_branch)
        stale_user = User.objects.create_user(username='old-offline', branch=old_branch)
        stale_pk = stale_user.pk
        stale_user.delete()
        self.admin.set_password('local-password')
        self.admin.save()
        job = replacement.stage_replacement(self.upload(data), self.admin)
        with self.assertRaisesMessage(backups.BackupError, 'تأكيد الاستعادة الكاملة'):
            backups.apply_import(job.pk, self.admin)
        result = replacement.apply_replacement(job.pk, self.admin)
        self.assertFalse(Branch.objects.filter(code=old_branch.code).exists())
        self.assertFalse(Product.all_objects.filter(sku=old_product.sku).exists())
        self.assertFalse(User.all_objects.filter(username=local_user.username).exists())
        restored_admin = User.all_objects.get(username=self.admin.username)
        self.assertGreater(restored_admin.pk, stale_pk)
        self.assertTrue(restored_admin.check_password('test-secret'))
        self.assertFalse(restored_admin.check_password('local-password'))
        branch = Branch.objects.get(code='SOURCE')
        self.assertGreater(branch.pk, old_branch.pk)
        self.assertEqual(Stock.all_objects.get(branch=branch).quantity, 17)
        self.assertEqual(CashAccount.all_objects.get(branch=branch).balance, Decimal('20'))
        order = Order.all_objects.get(branch=branch)
        self.assertEqual(order.items.get().variant.product.sku, 'SOURCE-P')
        self.assertEqual((self.media / str(order.items.get().variant.product.image)).read_bytes(), PNG)
        _, previous = backups.read_archive(backups.private_root() / result['recovery_name'])
        self.assertTrue(any(row['model'] == 'products.product' and row['fields']['sku'] == 'LOCAL-ONLY'
                            for row in previous))
        self.assertFalse(BackupImport.objects.filter(pk=job.pk).exists())

    def test_full_replacement_rejects_changed_destination_before_writing_safety_file(self):
        data, _ = self.make_source()
        job = replacement.stage_replacement(self.upload(data), self.admin)
        current = Product.objects.create(sku='AFTER-RESTORE-PREVIEW', name='Product after preview')
        with self.assertRaisesMessage(backups.BackupError, 'بعد المعاينة'):
            replacement.apply_replacement(job.pk, self.admin)
        self.assertTrue(Product.objects.filter(pk=current.pk).exists())
        self.assertFalse(list(backups.private_root().glob('pre-restore-*.zip')))

    def test_full_replacement_rejects_backup_without_usable_superuser(self):
        with transaction.atomic():
            User.all_objects.filter(pk=self.admin.pk).update(password='!')
            with backups.build_backup() as stream:
                data = stream.read()
            transaction.set_rollback(True)
        with self.assertRaisesMessage(backups.BackupError, 'مسؤول أعلى نشط'):
            replacement.stage_replacement(self.upload(data), self.admin)
        self.assertFalse(BackupImport.objects.exists())

    def test_full_replacement_failure_restores_current_database_and_media(self):
        data, _ = self.make_source()
        current = Product.objects.create(sku='RETAIN-ON-FAILURE', name='Current product')
        job = replacement.stage_replacement(self.upload(data), self.admin)
        with patch.object(replacement, '_save_recovery_file', side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):
                replacement.apply_replacement(job.pk, self.admin)
        self.assertTrue(Product.objects.filter(pk=current.pk).exists())

        install = backups._install_media

        def fail_after_install(*args):
            install(*args)
            raise OSError('media unavailable')

        with patch.object(backups, '_install_media', side_effect=fail_after_install):
            with self.assertRaises(OSError):
                replacement.apply_replacement(job.pk, self.admin)
        self.assertTrue(Product.objects.filter(pk=current.pk, sku=current.sku).exists())
        self.assertFalse(Product.all_objects.filter(sku='SOURCE-P').exists())
        self.assertTrue(User.all_objects.filter(pk=self.admin.pk).exists())
        self.assertTrue(BackupImport.objects.filter(pk=job.pk).exists())
        self.assertFalse((self.media / 'products/item.png').exists())
        self.assertFalse(list(backups.private_root().glob('pre-restore-*.zip')))

    def test_missing_migrations_show_an_actionable_page_without_a_download_link(self):
        self.client.force_login(self.admin)
        with patch.object(backups, 'MigrationExecutor') as executor:
            executor.return_value.migration_plan.return_value = [('settings_app.0009', False)]
            page = self.client.get(reverse('settings_app:backups'))
            self.assertContains(page, 'python manage.py migrate', status_code=400)
            self.assertNotContains(page, reverse('settings_app:backup_download'), status_code=400)
            self.assertNotContains(page, 'name="archive"', status_code=400)
            result = self.client.get(reverse('settings_app:backup_download'), follow=True)
            self.assertContains(result, 'python manage.py migrate', status_code=400)
            self.assertNotIn('Content-Disposition', result)

    def test_failed_download_displays_persistent_error_without_html_download_attribute(self):
        self.client.force_login(self.admin)
        with patch('settings_app.backup_views.build_backup', side_effect=backups.BackupError('تعذر تجهيز النسخة للاختبار')):
            result = self.client.get(reverse('settings_app:backup_download'), follow=True)
        self.assertContains(result, 'تعذر تجهيز النسخة للاختبار', status_code=400)
        self.assertContains(result, 'data-backup-error', status_code=400)
        self.assertContains(result, result['X-Request-ID'], status_code=400)
        self.assertEqual(result.redirect_chain, [])
        self.assertNotIn('Content-Disposition', result)
        self.assertNotContains(result, ' download', status_code=400)

    def test_server_failures_show_actionable_messages_without_internal_secrets(self):
        self.client.force_login(self.admin)
        cases = [(OSError(errno.ENOSPC, 'private disk path'), 503, 'مساحة كافية'),
                 (PermissionError(errno.EACCES, 'private disk path'), 503, 'صلاحية'),
                 (DatabaseError('no such table: private_table'), 503, 'ترحيلات'),
                 (KeyError('private internal value'), 500, 'KeyError')]
        for failure, status, expected in cases:
            with self.subTest(failure=type(failure).__name__), self.assertLogs('settings_app.backups', 'ERROR') as logs:
                with patch('settings_app.backup_views.build_backup', side_effect=failure):
                    result = self.client.get(reverse('settings_app:backup_download'))
            self.assertContains(result, expected, status_code=status)
            self.assertContains(result, 'data-backup-error', status_code=status)
            self.assertNotContains(result, 'private ', status_code=status)
            self.assertIn(result['X-Request-ID'], result.content.decode())
            self.assertIn('Backup operation failed', '\n'.join(logs.output))
            self.assertNotIn('Content-Disposition', result)

    def test_layout_database_failure_falls_back_to_standalone_error_with_reference(self):
        from .backup_views import backup_failure_response
        from django.test import RequestFactory
        request = RequestFactory().get('/settings/backups/download/')
        with patch('settings_app.backup_views.render', side_effect=DatabaseError('database unavailable')):
            with self.assertLogs('settings_app.backups', 'ERROR'):
                response = backup_failure_response(request, DatabaseError('database unavailable'), 'download')
        self.assertContains(response, 'قاعدة البيانات', status_code=503)
        self.assertContains(response, response['X-Request-ID'], status_code=503)
        self.assertIn('no-store', response['Cache-Control'])

    @override_settings(ERROR_EMAIL_ENABLED=True, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
                       ADMINS=[('Admin', 'admin@example.test')], SERVER_EMAIL='system@example.test')
    def test_unexpected_download_error_sends_email_with_the_displayed_reference(self):
        error_email._recent_alerts.clear()
        self.addCleanup(error_email._recent_alerts.clear)
        self.addCleanup(error_email._last_delivery.clear)
        mail.get_connection()
        mail.outbox.clear()
        self.client.force_login(self.admin)
        logger = logging.getLogger('settings_app.backups')
        handler = error_email.ErrorEmailHandler()
        handler.addFilter(SanitizingFilter())
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)
        # Django logs the HTTP 500 after RequestIdMiddleware resets its context.
        # It must share the original reference and send no second notification.
        response_logger = logging.getLogger('django.request')
        response_logger.disabled = False
        response_logger.addHandler(handler)
        self.addCleanup(response_logger.removeHandler, handler)
        with patch('settings_app.backup_views.build_backup', side_effect=KeyError('unexpected')):
            response = self.client.get(reverse('settings_app:backup_download'))
        self.assertContains(response, 'KeyError', status_code=500)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(response['X-Request-ID'], mail.outbox[0].body)

    @override_settings(ERROR_EMAIL_ENABLED=True, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
                       ADMINS=[('Admin', 'admin@example.test')], SERVER_EMAIL='system@example.test')
    def test_smtp_failure_does_not_hide_backup_error_and_explains_delivery_failure(self):
        error_email._recent_alerts.clear()
        self.addCleanup(error_email._recent_alerts.clear)
        self.addCleanup(error_email._last_delivery.clear)
        self.client.force_login(self.admin)
        logger = logging.getLogger('settings_app.backups')
        handler = error_email.ErrorEmailHandler()
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)
        with patch('settings_app.backup_views.build_backup', side_effect=OSError(errno.ENOSPC, 'disk full')):
            with patch('config.error_email.EmailMessage.send', side_effect=smtplib.SMTPAuthenticationError(535, b'bad login')):
                response = self.client.get(reverse('settings_app:backup_download'))
        self.assertContains(response, 'مساحة كافية', status_code=503)
        self.assertContains(response, 'رفض خادم SMTP تسجيل الدخول', status_code=503)

    @override_settings(BACKUP_MAX_UPLOAD_BYTES=0)
    def test_invalid_backup_limits_do_not_crash_error_rendering(self):
        self.client.force_login(self.admin)
        with self.assertLogs('settings_app.backups', 'ERROR'):
            response = self.client.get(reverse('settings_app:backups'))
        self.assertContains(response, 'أعدادًا موجبة', status_code=400)
        self.assertNotContains(response, 'name="archive"', status_code=400)


@skipUnlessDBFeature('has_select_for_update')
class BackupConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='sh-backup-concurrent-')
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.override = override_settings(MEDIA_ROOT=root / 'media', MEDIA_FALLBACK_ROOTS=[],
                                          BACKUP_PRIVATE_ROOT=root / 'private',
                                          PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.admin = User.objects.create_superuser(username='concurrent-backup-admin', password='test')
        Branch.objects.get_or_create(code='MAIN', defaults={'name': 'Main'})

    def parallel(self, callback):
        def run():
            try:
                return callback()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(run) for _ in range(2)]
            return [future.result(timeout=40) for future in futures]

    def test_simultaneous_downloads_assign_one_canonical_identity(self):
        with backups.build_backup():
            pass
        product = Product.objects.create(name='Concurrent product', sku='CONCURRENT')
        barrier = threading.Barrier(2)
        original = backups._global_uid

        def synchronized_uid(obj):
            if obj._meta.label_lower == 'products.product':
                barrier.wait(timeout=15)
            return original(obj)

        def download():
            for attempt in range(3):
                try:
                    with backups.build_backup() as stream, zipfile.ZipFile(stream) as archive:
                        records = json.loads(archive.read('data.json'))
                        return next(r['uid'] for r in records if r['model'] == 'products.product')
                except DatabaseError:
                    if attempt == 2:
                        raise

        with patch.object(backups, '_global_uid', side_effect=synchronized_uid):
            result = self.parallel(download)
        self.assertEqual(result[0], result[1])
        self.assertEqual(BackupIdentity.objects.filter(model_label='products.product',
                                                      object_pk=str(product.pk), is_primary=True).count(), 1)

    def test_simultaneous_confirmation_imports_once(self):
        with transaction.atomic():
            Product.objects.create(name='One import', sku='ONCE')
            with backups.build_backup() as stream:
                data = stream.read()
            transaction.set_rollback(True)
        job = backups.stage_upload(SimpleUploadedFile('backup.zip', data), self.admin)
        barrier = threading.Barrier(2)

        def apply():
            barrier.wait(timeout=15)
            return backups.apply_import(job.pk, self.admin).pk

        results = self.parallel(apply)
        self.assertEqual(results, [job.pk, job.pk])
        self.assertEqual(Product.all_objects.filter(sku='ONCE').count(), 1)
