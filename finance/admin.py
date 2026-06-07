from django.contrib import admin

from .models import CashAccount, PaymentTransaction


@admin.register(CashAccount)
class CashAccountAdmin(admin.ModelAdmin):
    list_display = ('name', 'account_type', 'assigned_user', 'balance', 'is_active')
    list_filter = ('account_type', 'is_active')
    search_fields = ('name', 'assigned_user__username')


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ('transaction_date', 'transaction_type', 'direction', 'amount', 'cash_account', 'related_order', 'created_at')
    list_filter = ('transaction_type', 'direction', 'cash_account', 'transaction_date')
    search_fields = ('reference', 'notes', 'related_order__order_number', 'related_customer__name')
