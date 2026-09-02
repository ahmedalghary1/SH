from django.contrib import admin

from .models import Customer, CustomerInteraction


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'customer_type', 'phone', 'company_name', 'sales_representative', 'credit_limit', 'opening_balance', 'is_active', 'created_by', 'created_at')
    list_filter = ('branch', 'customer_type', 'sales_representative', 'is_active', 'created_at')
    search_fields = ('name', 'phone', 'company_name', 'tax_number', 'sales_representative__username')


@admin.register(CustomerInteraction)
class CustomerInteractionAdmin(admin.ModelAdmin):
    list_display = ('customer', 'interaction_type', 'title', 'next_follow_up_date', 'is_completed', 'created_by', 'created_at')
    list_filter = ('branch', 'interaction_type', 'is_completed', 'next_follow_up_date', 'created_at')
    search_fields = ('customer__name', 'customer__phone', 'title', 'description')
