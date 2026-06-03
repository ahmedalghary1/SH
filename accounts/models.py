from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    ROLE_MANAGER = 'manager'
    ROLE_SALES = 'sales'
    ROLE_WAREHOUSE = 'warehouse'

    ROLE_CHOICES = [
        (ROLE_MANAGER, 'مسؤول النظام'),
        (ROLE_SALES, 'مندوب مبيعات'),
        (ROLE_WAREHOUSE, 'مسؤول مخزن'),
    ]

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_SALES, db_index=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['role', 'is_active']),
            models.Index(fields=['created_at']),
        ]

    @property
    def is_manager(self):
        return self.role == self.ROLE_MANAGER or self.is_superuser

    @property
    def is_sales(self):
        return self.role == self.ROLE_SALES

    @property
    def is_warehouse(self):
        return self.role == self.ROLE_WAREHOUSE

# Create your models here.
