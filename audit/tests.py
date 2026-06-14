from django.core.exceptions import PermissionDenied
from django.test import RequestFactory
from django.test import TestCase

from accounts.models import User
from audit.context import clear_current_request, set_current_request
from audit.models import AuditLog
from audit.services import log_audit
from products.models import Product


class AuditLogTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='manager', password='pass', role='manager')
        self.factory = RequestFactory()

    def tearDown(self):
        clear_current_request()
    
    def test_log_audit_creates_entry(self):
        log_audit(
            user=self.user,
            action=AuditLog.ACTION_CREATE,
            section=AuditLog.SECTION_ORDERS,
            model_name='Order',
            object_id='123',
            object_repr='ORD-123',
            notes='Test log entry',
        )
        
        log = AuditLog.objects.get()
        self.assertEqual(log.user, self.user)
        self.assertEqual(log.action, AuditLog.ACTION_CREATE)
        self.assertEqual(log.section, AuditLog.SECTION_ORDERS)
        self.assertEqual(log.model_name, 'Order')
        self.assertEqual(log.object_id, '123')
        self.assertEqual(log.object_repr, 'ORD-123')
        self.assertEqual(log.notes, 'Test log entry')
    
    def test_log_audit_with_changes(self):
        log_audit(
            user=self.user,
            action=AuditLog.ACTION_UPDATE,
            section=AuditLog.SECTION_PRODUCTS,
            model_name='ProductVariant',
            object_id='456',
            changes_before={'price': '100.00'},
            changes_after={'price': '120.00'},
            notes='Price update',
        )
        
        log = AuditLog.objects.get()
        self.assertEqual(log.changes_before, {'price': '100.00'})
        self.assertEqual(log.changes_after, {'price': '120.00'})
    
    def test_log_audit_without_user(self):
        log_audit(
            user=None,
            action=AuditLog.ACTION_CREATE,
            section=AuditLog.SECTION_INVENTORY,
            model_name='Stock',
            object_id='789',
            notes='System operation',
        )
        
        log = AuditLog.objects.get()
        self.assertIsNone(log.user)
        self.assertEqual(log.action, AuditLog.ACTION_CREATE)
    
    def test_audit_log_cannot_be_deleted(self):
        log = AuditLog.objects.create(
            user=self.user,
            action=AuditLog.ACTION_CREATE,
            section=AuditLog.SECTION_ORDERS,
            model_name='Order',
            object_id='123',
            object_repr='ORD-123',
        )
        
        with self.assertRaises(PermissionDenied) as cm:
            log.delete()
        
        self.assertIn('cannot be deleted', str(cm.exception))
        # Verify log still exists
        self.assertTrue(AuditLog.objects.filter(pk=log.pk).exists())
    
    def test_audit_log_cannot_be_modified(self):
        log = AuditLog.objects.create(
            user=self.user,
            action=AuditLog.ACTION_CREATE,
            section=AuditLog.SECTION_ORDERS,
            model_name='Order',
            object_id='123',
            object_repr='ORD-123',
            notes='Original note',
        )
        
        # Try to modify the log
        log.notes = 'Modified note'
        with self.assertRaises(PermissionDenied) as cm:
            log.save()
        
        self.assertIn('cannot be modified', str(cm.exception))
        # Verify note was not changed
        log.refresh_from_db()
        self.assertEqual(log.notes, 'Original note')
    
    def test_audit_log_can_be_created(self):
        """Verify that creating new audit logs still works."""
        log = AuditLog.objects.create(
            user=self.user,
            action=AuditLog.ACTION_CREATE,
            section=AuditLog.SECTION_ORDERS,
            model_name='Order',
            object_id='123',
            object_repr='ORD-123',
            notes='Test log entry',
        )
        
        self.assertEqual(log.user, self.user)
        self.assertEqual(log.action, AuditLog.ACTION_CREATE)
        self.assertEqual(log.notes, 'Test log entry')

    def test_model_update_is_logged_with_current_user(self):
        product = Product.objects.create(name='Shirt', sku='SH-001', retail_price='100.00')
        request = self.factory.post('/products/')
        request.user = self.user
        set_current_request(request)

        product.retail_price = '125.00'
        product.save()

        log = AuditLog.objects.get(action=AuditLog.ACTION_UPDATE)
        self.assertEqual(log.user, self.user)
        self.assertEqual(log.section, AuditLog.SECTION_PRODUCTS)
        self.assertEqual(log.model_name, 'Product')
        self.assertEqual(log.object_id, str(product.pk))
        self.assertEqual(log.changes_before['retail_price'], '100.00')
        self.assertEqual(log.changes_after['retail_price'], '125.00')

    def test_model_delete_is_logged_with_current_user(self):
        product = Product.objects.create(name='Deleted Shirt', sku='SH-DEL')
        request = self.factory.post('/products/delete/')
        request.user = self.user
        set_current_request(request)

        product_id = product.pk
        product.delete()

        log = AuditLog.objects.get(action=AuditLog.ACTION_DELETE)
        self.assertEqual(log.user, self.user)
        self.assertEqual(log.section, AuditLog.SECTION_PRODUCTS)
        self.assertEqual(log.model_name, 'Product')
        self.assertEqual(log.object_id, str(product_id))
        self.assertEqual(log.changes_before['sku'], 'SH-DEL')

