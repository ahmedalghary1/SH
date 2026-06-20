from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from customers.models import Customer
from orders.models import Order, OrderItem
from products.models import ProductVariant


class SalesReturn(models.Model):
    TYPE_REFUND = 'refund'
    TYPE_EXCHANGE = 'exchange'
    TYPE_PARTIAL_RETURN = 'partial_return'
    RETURN_TYPE_CHOICES = [
        (TYPE_REFUND, 'استرداد'),
        (TYPE_EXCHANGE, 'استبدال'),
        (TYPE_PARTIAL_RETURN, 'مرتجع جزئي'),
    ]

    STATUS_DRAFT = 'draft'
    STATUS_APPROVED = 'approved'
    STATUS_COMPLETED = 'completed'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'مسودة'),
        (STATUS_APPROVED, 'معتمد'),
        (STATUS_COMPLETED, 'مكتمل'),
        (STATUS_REJECTED, 'مرفوض'),
    ]

    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name='sales_returns')
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name='sales_returns')
    return_type = models.CharField(max_length=30, choices=RETURN_TYPE_CHOICES, default=TYPE_PARTIAL_RETURN, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)
    reason = models.TextField(blank=True, null=True)
    refund_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_sales_returns')
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_sales_returns')
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='completed_sales_returns')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['return_type', 'created_at']),
            models.Index(fields=['order', 'status']),
        ]

    def __str__(self):
        return f'RET-{self.pk or "new"} - {self.order}'


class SalesReturnItem(models.Model):
    CONDITION_GOOD = 'good'
    CONDITION_DAMAGED = 'damaged'
    CONDITION_NEEDS_REVIEW = 'needs_review'
    CONDITION_CHOICES = [
        (CONDITION_GOOD, 'سليم'),
        (CONDITION_DAMAGED, 'تالف'),
        (CONDITION_NEEDS_REVIEW, 'يحتاج مراجعة'),
    ]

    sales_return = models.ForeignKey(SalesReturn, on_delete=models.CASCADE, related_name='items')
    original_order_item = models.ForeignKey(OrderItem, on_delete=models.PROTECT, related_name='return_items')
    product_variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT, related_name='return_items')
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    check = models.CharField(max_length=30, choices=CONDITION_CHOICES, default=CONDITION_GOOD, db_index=True)
    return_to_stock = models.BooleanField(default=True)
    refund_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f'{self.sales_return_id} - {self.product_variant} - {self.quantity}'


class ExchangeItem(models.Model):
    sales_return = models.ForeignKey(SalesReturn, on_delete=models.CASCADE, related_name='exchange_items')
    old_order_item = models.ForeignKey(OrderItem, on_delete=models.PROTECT, related_name='exchange_items')
    new_product_variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT, related_name='exchange_items')
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    new_unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    old_unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    price_difference = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f'{self.sales_return_id} exchange {self.quantity}'
