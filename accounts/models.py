from django.contrib.auth.models import AbstractUser, UserManager
from django.conf import settings
from django.db import models
from config.branching import BranchOwnedModel, get_default_branch_id
from config.django_compat import check_constraint


class Branch(models.Model):
    name = models.CharField(max_length=150, db_index=True)
    code = models.CharField(max_length=30, unique=True, db_index=True)
    address = models.TextField(blank=True, null=True)
    phone = models.CharField(max_length=30, blank=True, null=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class BranchUserManager(UserManager):
    def get_queryset(self):
        queryset = super().get_queryset()
        from config.branching import branch_context_is_set, get_current_branch_id
        if branch_context_is_set() and get_current_branch_id() is not None:
            queryset = queryset.filter(branch_id=get_current_branch_id())
        return queryset


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
    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="users",
    )
    phone = models.CharField(max_length=20, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = BranchUserManager()
    all_objects = UserManager()

    class Meta:
        indexes = [
            models.Index(fields=['role', 'is_active']),
            models.Index(fields=['created_at']),
        ]
        constraints = [
            check_constraint(
                check=models.Q(is_superuser=True) | models.Q(branch__isnull=False),
                name='accounts_user_non_superuser_requires_branch',
            ),
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

    def save(self, *args, **kwargs):
        if not self.is_superuser and not self.branch_id:
            from config.branching import get_default_branch_id
            self.branch_id = get_default_branch_id()
        super().save(*args, **kwargs)


class SubmissionReceipt(BranchOwnedModel):
    token = models.CharField(max_length=64, unique=True, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='submission_receipts')
    path = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    def infer_branch_id(self):
        return self.user.branch_id if self.user_id else None

# Create your models here.
