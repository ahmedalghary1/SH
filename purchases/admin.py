from django.contrib import admin

from .models import PurchaseOrder, PurchaseOrderItem, Supplier


class PurchaseOrderItemInline(admin.TabularInline):
    model = PurchaseOrderItem
    extra = 0


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'company_name', 'phone', 'current_balance', 'is_active')
    list_filter = ('branch', 'is_active',)
    search_fields = ('name', 'company_name', 'phone')


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ('purchase_number', 'supplier', 'status', 'total_amount', 'paid_amount', 'remaining_amount')
    list_filter = ('branch', 'status', 'supplier')
    search_fields = ('purchase_number', 'supplier__name', 'supplier__company_name')
    inlines = [PurchaseOrderItemInline]
