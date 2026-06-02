from django.contrib import admin

from .models import Order, OrderItem


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('order_number', 'order_type', 'customer', 'warehouse', 'status', 'payment_status', 'total', 'created_by', 'created_at')
    list_filter = ('order_type', 'status', 'payment_status', 'payment_method', 'created_at')
    search_fields = ('order_number', 'customer__name', 'customer__phone')
    inlines = [OrderItemInline]


admin.site.register(OrderItem)

# Register your models here.
