from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from customers.models import Customer
from inventory.models import Warehouse
from products.models import ProductVariant


class Order(models.Model):
    TYPE_B2C = 'b2c'
    TYPE_B2B = 'b2b'
    ORDER_TYPE_CHOICES = [
        (TYPE_B2C, 'قطاعي'),
        (TYPE_B2B, 'جملة'),
    ]

    STATUS_DRAFT = 'draft'
    STATUS_CONFIRMED = 'confirmed'
    STATUS_PREPARING = 'preparing'
    STATUS_READY = 'ready'
    STATUS_COMPLETED = 'completed'
    STATUS_CANCELLED = 'cancelled'
    STATUS_PARTIALLY_RETURNED = 'partially_returned'
    STATUS_RETURNED = 'returned'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'مسودة'),
        (STATUS_CONFIRMED, 'مؤكد'),
        (STATUS_PREPARING, 'قيد التجهيز'),
        (STATUS_READY, 'جاهز'),
        (STATUS_COMPLETED, 'مكتمل'),
        (STATUS_CANCELLED, 'ملغي'),
        (STATUS_PARTIALLY_RETURNED, 'مرتجع جزئيا'),
        (STATUS_RETURNED, 'مرتجع'),
    ]

    PAYMENT_UNPAID = 'unpaid'
    PAYMENT_PARTIAL = 'partial'
    PAYMENT_PAID = 'paid'
    PAYMENT_STATUS_CHOICES = [
        (PAYMENT_UNPAID, 'غير مدفوع'),
        (PAYMENT_PARTIAL, 'مدفوع جزئيا'),
        (PAYMENT_PAID, 'مدفوع بالكامل'),
    ]

    METHOD_CASH = 'cash'
    METHOD_COD = 'cod'
    METHOD_BANK = 'bank_transfer'
    METHOD_WALLET = 'wallet_transfer'
    PAYMENT_METHOD_CHOICES = [
        (METHOD_CASH, 'نقدي'),
        (METHOD_COD, 'الدفع عند الاستلام'),
        (METHOD_BANK, 'تحويل بنكي مسجل يدويا'),
        (METHOD_WALLET, 'تحويل محفظة مسجل يدويا'),
    ]

    order_number = models.CharField(max_length=50, unique=True, db_index=True)
    order_type = models.CharField(max_length=10, choices=ORDER_TYPE_CHOICES)
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.SET_NULL, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default=PAYMENT_UNPAID, db_index=True)
    payment_method = models.CharField(max_length=30, choices=PAYMENT_METHOD_CHOICES, default=METHOD_CASH)
    wallet_from_number = models.CharField(max_length=50, blank=True, null=True)
    wallet_to_number = models.CharField(max_length=50, blank=True, null=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    discount_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    discount_reason = models.TextField(blank=True, null=True)
    discount_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_order_discounts',
    )
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gross_profit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    remaining_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['order_number']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return self.order_number

    @property
    def order_total_cost(self):
        return self.total_cost

    @property
    def order_gross_profit(self):
        return self.gross_profit

    @property
    def profit_margin_percentage(self):
        if self.total <= 0:
            return 0
        return (self.gross_profit / self.total) * 100


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    variant = models.ForeignKey(ProductVariant, on_delete=models.SET_NULL, null=True)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.SET_NULL, null=True, blank=True)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    original_unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    discount_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    final_unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    cost_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    profit_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def __str__(self):
        return f'{self.order.order_number} - {self.variant}'

    @property
    def item_total(self):
        return self.total

    @property
    def item_cost_total(self):
        return self.cost_total

    @property
    def item_profit(self):
        return self.profit_total
