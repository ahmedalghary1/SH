from django.contrib import admin

from .models import Category, Color, Product, ProductVariant, Size


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 1


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'sku', 'category', 'is_active')
    list_filter = ('category', 'is_active', 'season')
    search_fields = ('name', 'sku', 'variants__variant_sku', 'variants__barcode')
    inlines = [ProductVariantInline]


admin.site.register(Category)
admin.site.register(Color)
admin.site.register(Size)
admin.site.register(ProductVariant)

# Register your models here.
