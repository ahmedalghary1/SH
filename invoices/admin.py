from django.contrib import admin

from .models import Invoice


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('invoice_number', 'order', 'issued_at', 'printed_count')
    search_fields = ('invoice_number', 'order__order_number')
    list_filter = ('branch', 'issued_at')

# Register your models here.
