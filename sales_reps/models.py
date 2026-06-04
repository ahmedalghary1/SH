from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from customers.models import Customer
from finance.models import CashAccount
from inventory.models import Warehouse
from orders.models import Order
from products.models import ProductVariant


class SalesRepStockAssignment(models.Model):
    sales_rep = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='stock_assignments')
    product_variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT, related_name='sales_rep_assignments')
    source_warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='sales_rep_assignments')
    quantity_assigned = models.PositiveIntegerField(default=0)
    quantity_sold = models.PositiveIntegerField(default=0)
    quantity_returned = models.PositiveIntegerField(default=0)
    quantity_remaining = models.PositiveIntegerField(default=0)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_stock_assignments')
    assigned_at = models.DateTimeField(default=timezone.now, db_index=True)
    notes = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['sales_rep', 'is_active']),
            models.Index(fields=['product_variant', 'sales_rep']),
            models.Index(fields=['assigned_at']),
        ]

    def __str__(self):
        return f'{self.sales_rep} - {self.product_variant} - {self.quantity_remaining}'


class SalesRepCollection(models.Model):
    sales_rep = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='collections')
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name='sales_rep_collections')
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True, related_name='sales_rep_collections')
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0.01)])
    handed_over_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    cash_account = models.ForeignKey(CashAccount, on_delete=models.PROTECT, related_name='sales_rep_collections')
    collection_date = models.DateField(default=timezone.localdate, db_index=True)
    handed_over = models.BooleanField(default=False, db_index=True)
    handed_over_at = models.DateTimeField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_sales_rep_collections')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['sales_rep', 'handed_over']),
            models.Index(fields=['collection_date']),
            models.Index(fields=['order']),
        ]

    def __str__(self):
        return f'{self.sales_rep} - {self.amount}'

    @property
    def remaining_handover_amount(self):
        return max(self.amount - self.handed_over_amount, Decimal('0'))
