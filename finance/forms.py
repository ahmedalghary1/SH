from django import forms

from accounts.models import User
from customers.models import Customer
from orders.models import Order

from .models import CashAccount


class CashAccountForm(forms.ModelForm):
    class Meta:
        model = CashAccount
        fields = ('name', 'account_type', 'assigned_user', 'balance', 'allow_overdraft', 'is_active')
        labels = {
            'name': 'اسم الخزنة / الحساب',
            'account_type': 'نوع الحساب',
            'assigned_user': 'المندوب المسؤول',
            'balance': 'الرصيد الافتتاحي',
            'allow_overdraft': 'السماح برصيد سالب',
            'is_active': 'نشط',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['assigned_user'].queryset = User.objects.filter(role=User.ROLE_SALES, is_active=True)
        self.fields['assigned_user'].required = False

    def clean(self):
        cleaned = super().clean()
        account_type = cleaned.get('account_type')
        assigned_user = cleaned.get('assigned_user')
        if account_type == CashAccount.TYPE_SALES_REP_CASH and not assigned_user:
            self.add_error('assigned_user', 'اختر المندوب عند إنشاء عهدة مالية')
        if account_type != CashAccount.TYPE_SALES_REP_CASH and assigned_user:
            self.add_error('assigned_user', 'ربط المندوب متاح فقط لعهدة المندوب المالية')
        return cleaned


class ExpenseForm(forms.Form):
    cash_account = forms.ModelChoiceField(queryset=CashAccount.objects.filter(is_active=True), label='الخزنة')
    amount = forms.DecimalField(min_value=0.01, label='المبلغ')
    notes = forms.CharField(widget=forms.Textarea, required=False, label='بيان المصروف')


class CustomerCollectionForm(forms.Form):
    cash_account = forms.ModelChoiceField(queryset=CashAccount.objects.filter(is_active=True), label='الخزنة')
    customer = forms.ModelChoiceField(queryset=Customer.objects.filter(is_active=True), label='العميل', required=False)
    order = forms.ModelChoiceField(queryset=Order.objects.exclude(remaining_amount=0), label='الطلب', required=False)
    amount = forms.DecimalField(min_value=0.01, label='المبلغ')
    notes = forms.CharField(widget=forms.Textarea, required=False, label='ملاحظات')

    def clean(self):
        cleaned = super().clean()
        order = cleaned.get('order')
        customer = cleaned.get('customer')
        amount = cleaned.get('amount')
        if not order and not customer:
            raise forms.ValidationError('اختر طلبًا أو عميلًا لتسجيل التحصيل')
        if order and amount and amount > order.remaining_amount:
            self.add_error('amount', 'مبلغ التحصيل أكبر من المتبقي على الطلب')
        if order and not customer:
            cleaned['customer'] = order.customer
        return cleaned


class TransferForm(forms.Form):
    from_account = forms.ModelChoiceField(queryset=CashAccount.objects.filter(is_active=True), label='من خزنة')
    to_account = forms.ModelChoiceField(queryset=CashAccount.objects.filter(is_active=True), label='إلى خزنة')
    amount = forms.DecimalField(min_value=0.01, label='المبلغ')
    notes = forms.CharField(widget=forms.Textarea, required=False, label='ملاحظات')


class SalesRepStatementForm(forms.Form):
    sales_rep = forms.ModelChoiceField(queryset=User.objects.filter(role=User.ROLE_SALES, is_active=True), label='المندوب')
