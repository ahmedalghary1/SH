from django.contrib import admin

from .models import Customer


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'customer_type', 'phone', 'company_name', 'is_active', 'created_by', 'created_at')
    list_filter = ('customer_type', 'is_active', 'created_at')
    search_fields = ('name', 'phone', 'company_name', 'tax_number')

# Register your models here.
