from django.conf import settings
from django.core.validators import MinValueValidator
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
    quantity = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    min_quantity = models.IntegerField(default=0, validators=[MinValueValidator(0)])

    class Meta:
        indexes = [
            models.Index(fields=['warehouse', 'variant']),
            models.Index(fields=['quantity']),
        ]
        constraints = [
            models.UniqueConstraint(fields=['warehouse', 'variant'], name='stock_warehouse_variant_unique'),
            models.CheckConstraint(condition=models.Q(quantity__gte=0), name='stock_quantity_non_negative'),
            models.CheckConstraint(condition=models.Q(min_quantity__gte=0), name='stock_min_quantity_non_negative'),
        ]

    def __str__(self):
        return f'{self.warehouse} - {self.variant}: {self.quantity}'

    @property
    def is_low(self):
        return self.quantity <= self.min_quantity


class StockBatch(models.Model):
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name='stock_batches')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='stock_batches')
    received_quantity = models.PositiveIntegerField(default=0)
    remaining_quantity = models.PositiveIntegerField(default=0, db_index=True)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    source = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    note = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['variant', 'warehouse', 'remaining_quantity']),
            models.Index(fields=['received_at']),
        ]
        ordering = ['received_at', 'pk']

    def __str__(self):
        return f'{self.variant} - {self.unit_cost} - {self.remaining_quantity}'


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
    TYPE_SAMPLE = 'sample'

    MOVEMENT_TYPE_CHOICES = [
        (TYPE_IN, 'دخول مخزون'),
        (TYPE_OUT, 'خروج مخزون'),
        (TYPE_TRANSFER, 'تحويل بين مخازن'),
        (TYPE_SALE, 'بيع'),
        (TYPE_RETURN, 'مرتجع'),
        (TYPE_ADJUSTMENT, 'تسوية'),
        (TYPE_PURCHASE_RECEIVE, 'استلام شراء'),
        (TYPE_SALES_RETURN, 'مرتجع بيع'),
        (TYPE_DAMAGED_RETURN, 'مرتجع تالف'),
        (TYPE_EXCHANGE_OUT, 'خروج استبدال'),
        (TYPE_SALES_REP_ASSIGNMENT, 'تهيئة مندوب'),
        (TYPE_SALES_REP_RETURN, 'مرتجع مندوب'),
        (TYPE_SALES_REP_SALE, 'بيع مندوب'),
        (TYPE_SAMPLE, 'عينة / إصدار مجاني'),
    ]

    movement_type = models.CharField(max_length=20, choices=MOVEMENT_TYPE_CHOICES, db_index=True)
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE)
    from_warehouse = models.ForeignKey(Warehouse, on_delete=models.SET_NULL, null=True, blank=True, related_name='out_movements')
    to_warehouse = models.ForeignKey(Warehouse, on_delete=models.SET_NULL, null=True, blank=True, related_name='in_movements')
    batch = models.ForeignKey(StockBatch, on_delete=models.SET_NULL, null=True, blank=True, related_name='movements')
    quantity = models.IntegerField(validators=[MinValueValidator(1)])
    note = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['variant', 'created_at']),
            models.Index(fields=['from_warehouse', 'created_at']),
            models.Index(fields=['to_warehouse', 'created_at']),
            models.Index(fields=['movement_type', 'created_at']),
            models.Index(fields=['created_at']),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name='stock_movement_quantity_positive'),
        ]

    def __str__(self):
        return f'{self.get_movement_type_display()} - {self.variant} - {self.quantity}'

# Create your models here.
