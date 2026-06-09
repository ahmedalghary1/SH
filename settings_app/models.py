from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class CompanySettings(models.Model):
    company_name = models.CharField(max_length=200, default='شركة الملابس')
    phone = models.CharField(max_length=50, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    tax_number = models.CharField(max_length=100, blank=True, null=True)
    logo = models.ImageField(upload_to='settings/', blank=True, null=True)
    invoice_notes = models.TextField(blank=True, null=True)
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
        settings, _ = cls.objects.get_or_create(pk=1)
        return settings
