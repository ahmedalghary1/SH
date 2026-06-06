from django import forms

from accounts.models import User
from customers.models import Customer
from finance.models import CashAccount
from inventory.models import Warehouse
from orders.models import Order
from products.models import ProductVariant

from .models import SalesRepStockAssignment


def sales_rep_queryset():
    return User.objects.filter(role=User.ROLE_SALES, is_active=True)


class AssignStockForm(forms.Form):
    sales_rep = forms.ModelChoiceField(queryset=sales_rep_queryset(), label='المندوب')
    product_variant = forms.ModelChoiceField(
        queryset=ProductVariant.objects.filter(is_active=True).select_related('product', 'color', 'size'),
        widget=forms.Select(attrs={
            'data-stock-filter-target': 'id_source_warehouse',
            'data-stock-filter-scope': 'non_representative',
        }),
        label='الصنف',
    )
    source_warehouse = forms.ModelChoiceField(
        queryset=Warehouse.objects.filter(is_active=True).exclude(warehouse_type=Warehouse.TYPE_REPRESENTATIVE),
        label='من مخزن',
    )
    quantity = forms.IntegerField(min_value=1, label='الكمية')
    notes = forms.CharField(widget=forms.Textarea, required=False, label='ملاحظات')


class AssignmentActionForm(forms.Form):
    assignment = forms.ModelChoiceField(
        queryset=SalesRepStockAssignment.objects.filter(is_active=True).select_related('sales_rep', 'product_variant__product'),
        label='العهدة',
    )
    quantity = forms.IntegerField(min_value=1, label='الكمية')
    notes = forms.CharField(widget=forms.Textarea, required=False, label='ملاحظات')


class SalesRepCollectionForm(forms.Form):
    sales_rep = forms.ModelChoiceField(queryset=sales_rep_queryset(), label='المندوب')
    customer = forms.ModelChoiceField(queryset=Customer.objects.filter(is_active=True), required=False, label='العميل')
    order = forms.ModelChoiceField(queryset=Order.objects.exclude(remaining_amount=0), required=False, label='الطلب')
    cash_account = forms.ModelChoiceField(queryset=CashAccount.objects.filter(is_active=True), required=False, label='حساب العهدة النقدية')
    amount = forms.DecimalField(min_value=0.01, label='المبلغ')
    notes = forms.CharField(widget=forms.Textarea, required=False, label='ملاحظات')


class SalesRepHandoverForm(forms.Form):
    sales_rep = forms.ModelChoiceField(queryset=sales_rep_queryset(), label='المندوب')
    source_cash_account = forms.ModelChoiceField(
        queryset=CashAccount.objects.filter(is_active=True, account_type=CashAccount.TYPE_SALES_REP_CASH),
        required=False,
        label='من حساب المندوب',
    )
    target_cash_account = forms.ModelChoiceField(
        queryset=CashAccount.objects.filter(is_active=True).exclude(account_type=CashAccount.TYPE_SALES_REP_CASH),
        label='إلى خزنة الإدارة',
    )
    amount = forms.DecimalField(min_value=0.01, label='المبلغ')
    notes = forms.CharField(widget=forms.Textarea, required=False, label='ملاحظات')


class SalesRepStatementForm(forms.Form):
    sales_rep = forms.ModelChoiceField(queryset=sales_rep_queryset(), label='المندوب')
