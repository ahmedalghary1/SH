from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class Customer(models.Model):
    TYPE_B2C = 'b2c'
    TYPE_B2B = 'b2b'
    TYPE_RETAIL = 'retail'
    TYPE_WHOLESALE = 'wholesale'
    TYPE_INACTIVE = 'inactive'
    TYPE_POTENTIAL = 'potential'
    TYPE_PROBLEM = 'problem_customer'
    CUSTOMER_TYPE_CHOICES = [
        (TYPE_B2C, 'عميل فردي'),
        (TYPE_B2B, 'عميل جملة / شركة'),
        (TYPE_RETAIL, 'قطاعي'),
        (TYPE_WHOLESALE, 'جملة'),
        (TYPE_INACTIVE, 'غير نشط'),
        (TYPE_POTENTIAL, 'محتمل'),
        (TYPE_PROBLEM, 'عميل يحتاج متابعة'),
    ]

    name = models.CharField(max_length=200, db_index=True)
    customer_type = models.CharField(max_length=30, choices=CUSTOMER_TYPE_CHOICES, default=TYPE_RETAIL, db_index=True)
    phone = models.CharField(max_length=20, db_index=True)
    whatsapp = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    company_name = models.CharField(max_length=200, blank=True, null=True)
    tax_number = models.CharField(max_length=100, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    credit_limit = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['phone']),
            models.Index(fields=['name', 'phone']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f'{self.name} - {self.phone}'


class CustomerInteraction(models.Model):
    TYPE_CALL = 'call'
    TYPE_WHATSAPP = 'whatsapp'
    TYPE_VISIT = 'visit'
    TYPE_NOTE = 'note'
    TYPE_COMPLAINT = 'complaint'
    TYPE_FOLLOW_UP = 'follow_up'
    INTERACTION_TYPE_CHOICES = [
        (TYPE_CALL, 'مكالمة'),
        (TYPE_WHATSAPP, 'واتساب'),
        (TYPE_VISIT, 'زيارة'),
        (TYPE_NOTE, 'ملاحظة'),
        (TYPE_COMPLAINT, 'شكوى'),
        (TYPE_FOLLOW_UP, 'متابعة'),
    ]

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='interactions')
    interaction_type = models.CharField(max_length=30, choices=INTERACTION_TYPE_CHOICES, default=TYPE_NOTE, db_index=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)
    next_follow_up_date = models.DateField(blank=True, null=True, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='customer_interactions')
    is_completed = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['customer', 'created_at']),
            models.Index(fields=['interaction_type', 'is_completed']),
            models.Index(fields=['next_follow_up_date', 'is_completed']),
        ]

    def __str__(self):
        return f'{self.customer} - {self.title}'
