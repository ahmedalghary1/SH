from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.db import models


class User(AbstractUser):
    ROLE_MANAGER = 'manager'
    ROLE_DIRECTOR = 'director'
    ROLE_SALES = 'sales'
    ROLE_WAREHOUSE = 'warehouse'

    ROLE_CHOICES = [
        (ROLE_MANAGER, 'مسؤول النظام'),
        (ROLE_DIRECTOR, 'المدير'),
        (ROLE_SALES, 'مندوب مبيعات'),
        (ROLE_WAREHOUSE, 'مسؤول مخزن'),
    ]

    username = models.CharField(
        'اسم المستخدم',
        max_length=150,
        unique=True,
        help_text='يمكن استخدام الحروف والأرقام والمسافات.',
        error_messages={'unique': 'يوجد مستخدم بهذا الاسم بالفعل.'},
    )
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
        return self.role in {self.ROLE_MANAGER, self.ROLE_DIRECTOR} or self.is_superuser

    @property
    def is_director(self):
        return self.role == self.ROLE_DIRECTOR

    @property
    def can_hard_delete(self):
        return self.role == self.ROLE_MANAGER or self.is_superuser

    @property
    def is_sales(self):
        return self.role == self.ROLE_SALES

    @property
    def is_warehouse(self):
        return self.role == self.ROLE_WAREHOUSE


class SubmissionReceipt(models.Model):
    token = models.CharField(max_length=64, unique=True, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='submission_receipts')
    path = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

# Create your models here.
