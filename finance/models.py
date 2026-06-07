from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from customers.models import Customer
from orders.models import Order


class CashAccount(models.Model):
    TYPE_CASH = 'cash'
    TYPE_BANK = 'bank'
    TYPE_WALLET = 'wallet'
    TYPE_SALES_REP_CASH = 'sales_rep_cash'
    ACCOUNT_TYPE_CHOICES = [
        (TYPE_CASH, 'خزنة نقدية'),
        (TYPE_BANK, 'حساب بنكي'),
        (TYPE_WALLET, 'محفظة إلكترونية'),
        (TYPE_SALES_REP_CASH, 'عهدة مندوب مالية'),
    ]

    name = models.CharField(max_length=120, db_index=True)
    account_type = models.CharField(max_length=30, choices=ACCOUNT_TYPE_CHOICES, default=TYPE_CASH, db_index=True)
    assigned_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cash_accounts',
    )
    balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    allow_overdraft = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['account_type', 'is_active']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return self.name

    @classmethod
    def get_default(cls):
        account, _ = cls.objects.get_or_create(
            name='الخزنة الرئيسية',
            defaults={'account_type': cls.TYPE_CASH, 'is_active': True},
        )
        return account


class PaymentTransaction(models.Model):
    TYPE_CUSTOMER_PAYMENT = 'customer_payment'
    TYPE_SUPPLIER_PAYMENT = 'supplier_payment'
    TYPE_EXPENSE = 'expense'
    TYPE_REFUND = 'refund'
    TYPE_SALES_REP_COLLECTION = 'sales_rep_collection'
    TYPE_SALES_REP_HANDOVER = 'sales_rep_handover'
    TYPE_TRANSFER = 'transfer'
    TYPE_ADJUSTMENT = 'adjustment'
    TRANSACTION_TYPE_CHOICES = [
        (TYPE_CUSTOMER_PAYMENT, 'تحصيل من عميل'),
        (TYPE_SUPPLIER_PAYMENT, 'دفع لمورد'),
        (TYPE_EXPENSE, 'مصروف'),
        (TYPE_REFUND, 'استرداد للعميل'),
        (TYPE_SALES_REP_COLLECTION, 'تحصيل مندوب'),
        (TYPE_TRANSFER, 'تحويل بين الخزن'),
        (TYPE_ADJUSTMENT, 'تسوية رصيد'),
    ]

    TRANSACTION_TYPE_CHOICES.append((TYPE_SALES_REP_HANDOVER, 'Sales rep handover'))

    DIRECTION_IN = 'in'
    DIRECTION_OUT = 'out'
    DIRECTION_CHOICES = [
        (DIRECTION_IN, 'داخل'),
        (DIRECTION_OUT, 'خارج'),
    ]

    transaction_type = models.CharField(max_length=40, choices=TRANSACTION_TYPE_CHOICES, db_index=True)
    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES, db_index=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0.01)])
    cash_account = models.ForeignKey(CashAccount, on_delete=models.PROTECT, related_name='transactions')
    related_order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True, related_name='payment_transactions')
    related_customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name='payment_transactions')
    related_sales_rep = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sales_rep_transactions',
    )
    related_supplier = models.ForeignKey(
        'purchases.Supplier',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payment_transactions',
    )
    related_supplier_name = models.CharField(max_length=200, blank=True, null=True)
    reference = models.CharField(max_length=80, blank=True, null=True, db_index=True)
    notes = models.TextField(blank=True, null=True)
    transaction_date = models.DateField(default=timezone.localdate, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['transaction_type', 'created_at']),
            models.Index(fields=['direction', 'created_at']),
            models.Index(fields=['cash_account', 'created_at']),
            models.Index(fields=['related_order']),
            models.Index(fields=['related_customer']),
            models.Index(fields=['related_supplier']),
        ]

    def __str__(self):
        return f'{self.get_transaction_type_display()} - {self.amount}'
