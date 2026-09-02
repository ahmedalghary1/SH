from django.contrib import admin

from .models import SalesRepCollection, SalesRepStockAssignment


@admin.register(SalesRepStockAssignment)
class SalesRepStockAssignmentAdmin(admin.ModelAdmin):
    list_display = ('sales_rep', 'product_variant', 'source_warehouse', 'quantity_assigned', 'quantity_sold', 'quantity_returned', 'quantity_remaining', 'is_active')
    list_filter = ('branch', 'is_active', 'sales_rep', 'source_warehouse')
    search_fields = ('sales_rep__username', 'product_variant__variant_sku', 'product_variant__product__name')


@admin.register(SalesRepCollection)
class SalesRepCollectionAdmin(admin.ModelAdmin):
    list_display = ('sales_rep', 'customer', 'order', 'amount', 'handed_over_amount', 'handed_over', 'collection_date')
    list_filter = ('branch', 'handed_over', 'sales_rep', 'collection_date')
    search_fields = ('sales_rep__username', 'customer__name', 'order__order_number')
