from django.conf import settings
from django.db import models

from products.models import ProductVariant


class Warehouse(models.Model):
    TYPE_MAIN = 'main'
    TYPE_STORE = 'store'
    TYPE_REPRESENTATIVE = 'representative'
    WAREHOUSE_TYPE_CHOICES = [
        (TYPE_MAIN, 'مخزن رئيسي'),
        (TYPE_STORE, 'محل بيع'),
        (TYPE_REPRESENTATIVE, 'عهدة مندوب'),
    ]

    name = models.CharField(max_length=100, db_index=True)
    warehouse_type = models.CharField(max_length=20, choices=WAREHOUSE_TYPE_CHOICES, db_index=True)
    assigned_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_warehouses',
    )
    address = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True, db_index=True)

    def __str__(self):
        return self.name


class Stock(models.Model):
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE)
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE)
    quantity = models.IntegerField(default=0)
    min_quantity = models.IntegerField(default=0)

    class Meta:
        unique_together = ('warehouse', 'variant')
        indexes = [
            models.Index(fields=['warehouse', 'variant']),
            models.Index(fields=['quantity']),
        ]

    def __str__(self):
        return f'{self.warehouse} - {self.variant}: {self.quantity}'

    @property
    def is_low(self):
        return self.quantity <= self.min_quantity


class StockMovement(models.Model):
    TYPE_IN = 'in'
    TYPE_OUT = 'out'
    TYPE_TRANSFER = 'transfer'
    TYPE_SALE = 'sale'
    TYPE_RETURN = 'return'
    TYPE_ADJUSTMENT = 'adjustment'
    TYPE_PURCHASE_RECEIVE = 'purchase_receive'
    TYPE_SALES_RETURN = 'sales_return'
    TYPE_DAMAGED_RETURN = 'damaged_return'
    TYPE_EXCHANGE_OUT = 'exchange_out'
    TYPE_SALES_REP_ASSIGNMENT = 'sales_rep_assignment'
    TYPE_SALES_REP_RETURN = 'sales_rep_return'
    TYPE_SALES_REP_SALE = 'sales_rep_sale'

    MOVEMENT_TYPE_CHOICES = [
        (TYPE_IN, 'دخول مخزون'),
        (TYPE_OUT, 'خروج مخزون'),
        (TYPE_TRANSFER, 'تحويل بين مخازن'),
        (TYPE_SALE, 'بيع'),
        (TYPE_RETURN, 'مرتجع'),
        (TYPE_ADJUSTMENT, 'تسوية'),
    ]

    MOVEMENT_TYPE_CHOICES.append((TYPE_PURCHASE_RECEIVE, 'Purchase receive'))
    MOVEMENT_TYPE_CHOICES.append((TYPE_SALES_RETURN, 'Sales return'))
    MOVEMENT_TYPE_CHOICES.append((TYPE_DAMAGED_RETURN, 'Damaged return'))
    MOVEMENT_TYPE_CHOICES.append((TYPE_EXCHANGE_OUT, 'Exchange out'))
    MOVEMENT_TYPE_CHOICES.append((TYPE_SALES_REP_ASSIGNMENT, 'Sales rep assignment'))
    MOVEMENT_TYPE_CHOICES.append((TYPE_SALES_REP_RETURN, 'Sales rep return'))
    MOVEMENT_TYPE_CHOICES.append((TYPE_SALES_REP_SALE, 'Sales rep sale'))

    movement_type = models.CharField(max_length=20, choices=MOVEMENT_TYPE_CHOICES, db_index=True)
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE)
    from_warehouse = models.ForeignKey(Warehouse, on_delete=models.SET_NULL, null=True, blank=True, related_name='out_movements')
    to_warehouse = models.ForeignKey(Warehouse, on_delete=models.SET_NULL, null=True, blank=True, related_name='in_movements')
    quantity = models.IntegerField()
    note = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['movement_type', 'created_at']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f'{self.get_movement_type_display()} - {self.variant} - {self.quantity}'

# Create your models here.
