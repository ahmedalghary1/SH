from django.contrib import admin

from .models import ExchangeItem, SalesReturn, SalesReturnItem


class SalesReturnItemInline(admin.TabularInline):
    model = SalesReturnItem
    extra = 0


class ExchangeItemInline(admin.TabularInline):
    model = ExchangeItem
    extra = 0


@admin.register(SalesReturn)
class SalesReturnAdmin(admin.ModelAdmin):
    list_display = ('id', 'order', 'return_type', 'status', 'refund_amount', 'created_at')
    list_filter = ('return_type', 'status')
    search_fields = ('order__order_number', 'customer__name')
    inlines = [SalesReturnItemInline, ExchangeItemInline]
