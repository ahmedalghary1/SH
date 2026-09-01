from django.core.validators import MinValueValidator
from django.db import models

from config.django_compat import check_constraint


class Category(models.Model):
    name = models.CharField(max_length=100, db_index=True)
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        verbose_name_plural = 'Categories'

    def __str__(self):
        return self.name


class Color(models.Model):
    name = models.CharField(max_length=50, unique=True)
    hex_code = models.CharField(max_length=7, blank=True, null=True)

    def __str__(self):
        return self.name


class Size(models.Model):
    name = models.CharField(max_length=20, unique=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name


class Product(models.Model):
    name = models.CharField(max_length=200, db_index=True)
    sku = models.CharField(max_length=100, unique=True, db_index=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True)
    agent = models.CharField(max_length=200, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    material = models.CharField(max_length=100, blank=True, null=True)
    season = models.CharField(max_length=100, blank=True, null=True)
    retail_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    wholesale_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    pieces_per_dozen = models.PositiveIntegerField(default=12, validators=[MinValueValidator(1)])
    image = models.ImageField(upload_to='products/', blank=True, null=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['sku']),
            models.Index(fields=['name', 'is_active']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f'{self.name} ({self.sku})'


class ProductVariant(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    color = models.ForeignKey(Color, on_delete=models.SET_NULL, null=True)
    size = models.ForeignKey(Size, on_delete=models.SET_NULL, null=True)
    image = models.ImageField(upload_to='product_variants/', blank=True, null=True)
    variant_sku = models.CharField(max_length=120, unique=True, db_index=True)
    barcode = models.CharField(max_length=120, blank=True, null=True, db_index=True)
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    sale_price = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    retail_price = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    wholesale_price = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    is_active = models.BooleanField(default=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['variant_sku']),
            models.Index(fields=['barcode']),
            models.Index(fields=['is_active']),
        ]
        constraints = [
            check_constraint(
                check=models.Q(cost_price__gte=0),
                name='products_productvariant_cost_price_gte_0'
            ),
            check_constraint(
                check=models.Q(sale_price__gte=0),
                name='products_productvariant_sale_price_gte_0'
            ),
        ]

    def __str__(self):
        return f'{self.product.name} - {self.color} - {self.size}'

    @property
    def retail_profit_per_piece(self):
        return self.effective_sale_price - self.cost_price

    @property
    def wholesale_profit_per_piece(self):
        return self.effective_sale_price - self.cost_price

    @property
    def effective_sale_price(self):
        return self.retail_price or self.sale_price

    @property
    def retail_profit_margin_percentage(self):
        if self.effective_sale_price <= 0:
            return 0
        return (self.retail_profit_per_piece / self.effective_sale_price) * 100

    @property
    def wholesale_profit_margin_percentage(self):
        if self.effective_sale_price <= 0:
            return 0
        return (self.wholesale_profit_per_piece / self.effective_sale_price) * 100

# Create your models here.
