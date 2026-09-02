from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import models
from config.branching import BranchOwnedModel


class AuditLog(BranchOwnedModel):
    """Audit log for tracking sensitive operations."""
    
    ACTION_CREATE = 'create'
    ACTION_UPDATE = 'update'
    ACTION_DELETE = 'delete'
    ACTION_CONFIRM = 'confirm'
    ACTION_CANCEL = 'cancel'
    ACTION_RETURN = 'return'
    ACTION_RECEIVE = 'receive'
    ACTION_PAY = 'pay'
    ACTION_COLLECT = 'collect'
    ACTION_HANDOVER = 'handover'
    ACTION_ASSIGN = 'assign'
    ACTION_ADJUST = 'adjust'
    ACTION_TRANSFER = 'transfer'
    
    ACTION_CHOICES = [
        (ACTION_CREATE, 'إنشاء'),
        (ACTION_UPDATE, 'تعديل'),
        (ACTION_DELETE, 'حذف'),
        (ACTION_CONFIRM, 'تأكيد'),
        (ACTION_CANCEL, 'إلغاء'),
        (ACTION_RETURN, 'مرتجع'),
        (ACTION_RECEIVE, 'استلام'),
        (ACTION_PAY, 'دفع'),
        (ACTION_COLLECT, 'تحصيل'),
        (ACTION_HANDOVER, 'تسليم عهدة'),
        (ACTION_ASSIGN, 'تعيين'),
        (ACTION_ADJUST, 'تسوية'),
        (ACTION_TRANSFER, 'تحويل'),
    ]
    
    SECTION_PRODUCTS = 'products'
    SECTION_ORDERS = 'orders'
    SECTION_INVENTORY = 'inventory'
    SECTION_PURCHASES = 'purchases'
    SECTION_RETURNS = 'returns'
    SECTION_FINANCE = 'finance'
    SECTION_CUSTOMERS = 'customers'
    SECTION_SALES_REPS = 'sales_reps'
    SECTION_SETTINGS = 'settings'
    SECTION_ACCOUNTS = 'accounts'
    SECTION_INVOICES = 'invoices'
    
    SECTION_CHOICES = [
        (SECTION_PRODUCTS, 'المنتجات'),
        (SECTION_ORDERS, 'الطلبات'),
        (SECTION_INVENTORY, 'المخزون'),
        (SECTION_PURCHASES, 'المشتريات'),
        (SECTION_RETURNS, 'المرتجعات'),
        (SECTION_FINANCE, 'المالية'),
        (SECTION_CUSTOMERS, 'العملاء'),
        (SECTION_SALES_REPS, 'المندوبين'),
        (SECTION_SETTINGS, 'الإعدادات'),
        (SECTION_ACCOUNTS, 'الحسابات'),
        (SECTION_INVOICES, 'الفواتير'),
    ]
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='audit_logs',
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES, db_index=True)
    section = models.CharField(max_length=20, choices=SECTION_CHOICES, db_index=True)
    model_name = models.CharField(max_length=100, blank=True, null=True)
    object_id = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    object_repr = models.CharField(max_length=200, blank=True, null=True)
    changes_before = models.JSONField(blank=True, null=True)
    changes_after = models.JSONField(blank=True, null=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['section', 'created_at']),
            models.Index(fields=['action', 'created_at']),
            models.Index(fields=['model_name', 'object_id']),
        ]
        verbose_name = 'سجل تدقيق'
        verbose_name_plural = 'سجلات التدقيق'
    
    def __str__(self):
        return f'{self.get_action_display()} - {self.get_section_display()} - {self.object_repr or self.object_id}'
    
    def delete(self, *args, **kwargs):
        """Prevent deletion of audit logs."""
        raise PermissionDenied('Audit logs cannot be deleted')
    
    def save(self, *args, **kwargs):
        """Prevent modification of existing audit logs."""
        if self.pk and not self._state.adding:
            raise PermissionDenied('Audit logs cannot be modified')
        super().save(*args, **kwargs)

    def infer_branch_id(self):
        return self.user.branch_id if self.user_id else None
