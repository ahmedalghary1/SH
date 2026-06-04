from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from products.models import ProductVariant


class Supplier(models.Model):
    name = models.CharField(max_length=200, db_index=True)
    phone = models.CharField(max_length=30, blank=True, null=True, db_index=True)
    email = models.EmailField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    company_name = models.CharField(max_length=200, blank=True, null=True)
    opening_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    current_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    notes = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['name', 'is_active']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return self.company_name or self.name


class PurchaseOrder(models.Model):
    STATUS_DRAFT = 'draft'
    STATUS_ORDERED = 'ordered'
    STATUS_PARTIALLY_RECEIVED = 'partially_received'
    STATUS_RECEIVED = 'received'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'مسودة'),
        (STATUS_ORDERED, 'تم الطلب'),
        (STATUS_PARTIALLY_RECEIVED, 'مستلم جزئيًا'),
        (STATUS_RECEIVED, 'مستلم بالكامل'),
        (STATUS_CANCELLED, 'ملغي'),
    ]

    purchase_number = models.CharField(max_length=50, unique=True, db_index=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='purchase_orders')
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)
    order_date = models.DateField(default=timezone.localdate, db_index=True)
    expected_date = models.DateField(blank=True, null=True)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    paid_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    remaining_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    notes = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['purchase_number']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['supplier', 'created_at']),
        ]

    def __str__(self):
        return self.purchase_number

    @property
    def is_editable(self):
        return self.status == self.STATUS_DRAFT


class PurchaseOrderItem(models.Model):
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='items')
    product_variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT, related_name='purchase_items')
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    received_quantity = models.PositiveIntegerField(default=0)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    total_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        indexes = [
            models.Index(fields=['purchase_order', 'product_variant']),
        ]

    def __str__(self):
        return f'{self.purchase_order.purchase_number} - {self.product_variant}'

    @property
    def remaining_quantity(self):
        return max(self.quantity - self.received_quantity, 0)
