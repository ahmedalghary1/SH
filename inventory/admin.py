from django.contrib import admin

from .models import Stock, StockMovement, Warehouse


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ('name', 'branch', 'warehouse_type', 'is_active')
    list_filter = ('branch', 'warehouse_type', 'is_active')
    search_fields = ('name',)


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ('warehouse', 'branch', 'variant', 'quantity', 'min_quantity')
    list_filter = ('branch', 'warehouse',)
    search_fields = ('variant__product__name', 'variant__variant_sku')


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ('movement_type', 'variant', 'from_warehouse', 'to_warehouse', 'quantity', 'created_by', 'created_at')
    list_filter = ('branch', 'movement_type', 'created_at')
    search_fields = ('variant__product__name', 'variant__variant_sku')
    


