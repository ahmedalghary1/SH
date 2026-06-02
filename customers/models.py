from django.conf import settings
from django.db import models


class Customer(models.Model):
    TYPE_B2C = 'b2c'
    TYPE_B2B = 'b2b'
    CUSTOMER_TYPE_CHOICES = [
        (TYPE_B2C, 'عميل فردي'),
        (TYPE_B2B, 'عميل جملة / شركة'),
    ]

    name = models.CharField(max_length=200, db_index=True)
    customer_type = models.CharField(max_length=10, choices=CUSTOMER_TYPE_CHOICES, db_index=True)
    phone = models.CharField(max_length=20, db_index=True)
    whatsapp = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    company_name = models.CharField(max_length=200, blank=True, null=True)
    tax_number = models.CharField(max_length=100, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
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

# Create your models here.
