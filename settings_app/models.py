import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from config.branching import BranchOwnedModel


class CompanySettings(BranchOwnedModel):
    THERMAL_WIDTH_58 = '58'
    THERMAL_WIDTH_80 = '80'
    THERMAL_PAPER_WIDTH_CHOICES = (
        (THERMAL_WIDTH_80, '80 مم'),
        (THERMAL_WIDTH_58, '58 مم'),
    )
    PRINT_MODE_BROWSER = 'browser'
    PRINT_MODE_ELECTRON = 'electron'
    PRINT_MODE_QZ = 'qz'
    THERMAL_PRINT_MODE_CHOICES = (
        (PRINT_MODE_BROWSER, 'طباعة المتصفح'),
        (PRINT_MODE_ELECTRON, 'طباعة مباشرة عبر تطبيق سطح المكتب'),
        (PRINT_MODE_QZ, 'طباعة مباشرة عبر QZ Tray'),
    )
    THERMAL_FONT_NORMAL = '100'
    THERMAL_FONT_LARGE = '115'
    THERMAL_FONT_XLARGE = '130'
    THERMAL_INVOICE_FONT_CHOICES = (
        (THERMAL_FONT_NORMAL, 'عادي'),
        (THERMAL_FONT_LARGE, 'كبير'),
        (THERMAL_FONT_XLARGE, 'كبير جدًا'),
    )

    company_name = models.CharField(max_length=200, default='شركة الملابس')
    phone = models.CharField(max_length=50, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    tax_number = models.CharField(max_length=100, blank=True, null=True)
    logo = models.ImageField(upload_to='settings/', blank=True, null=True)
    invoice_notes = models.TextField(blank=True, null=True)
    thermal_paper_width = models.CharField(max_length=2, choices=THERMAL_PAPER_WIDTH_CHOICES, default=THERMAL_WIDTH_80)
    thermal_invoice_font_scale = models.CharField(max_length=3, choices=THERMAL_INVOICE_FONT_CHOICES, default=THERMAL_FONT_LARGE)
    thermal_print_mode = models.CharField(max_length=16, choices=THERMAL_PRINT_MODE_CHOICES, default=PRINT_MODE_BROWSER)
    thermal_printer_name = models.CharField(max_length=200, blank=True, null=True)
    max_sales_discount_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=10, validators=[MinValueValidator(0), MaxValueValidator(100)])
    allow_manager_sell_below_cost = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'إعدادات الشركة'
        verbose_name_plural = 'إعدادات الشركة'

    def __str__(self):
        return self.company_name

    @classmethod
    def load(cls):
        settings = cls.objects.order_by('pk').first()
        if settings is None:
            settings = cls.objects.create()
        return settings


class BackupIdentity(models.Model):
    """Portable record identities, separate from database-specific primary keys."""

    uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    model_label = models.CharField(max_length=100)
    object_pk = models.CharField(max_length=100)
    is_primary = models.BooleanField(default=False)

    class Meta:
        indexes = [models.Index(fields=['model_label', 'object_pk'], name='settings_ap_model_l_5fa9bf_idx')]
        constraints = [models.UniqueConstraint(fields=['model_label', 'object_pk'], condition=models.Q(is_primary=True),
                                               name='backup_one_primary_identity')]


class BackupBranchHistory(models.Model):
    branch = models.OneToOneField('accounts.Branch', on_delete=models.CASCADE)
    digest = models.CharField(max_length=64)
    ancestors = models.JSONField(default=list)


class BackupImport(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    original_name = models.CharField(max_length=255)
    archive_digest = models.CharField(max_length=64)
    preview_digest = models.CharField(max_length=64)
    summary = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
