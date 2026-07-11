from django import forms
from django.utils import timezone

from accounts.models import User
from customers.models import Customer
from customers.services import visible_customers_for_user
from orders.models import Order
from purchases.models import Supplier

from .models import CashAccount


class CashAccountForm(forms.ModelForm):
    class Meta:
        model = CashAccount
        fields = ('name', 'account_type', 'assigned_user', 'balance', 'allow_overdraft', 'is_active')
        labels = {
            'name': 'اسم الخزنة / الحساب',
            'balance': 'الرصيد الافتتاحي',
            'allow_overdraft': 'السماح برصيد سالب',
            'is_active': 'نشط',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['assigned_user'].queryset = User.objects.filter(
            role=User.ROLE_SALES,
            is_active=True,
        ).order_by('username')
        self.fields['assigned_user'].required = False
        self.fields['assigned_user'].label = 'المندوب'

    def clean(self):
        cleaned = super().clean()
        account_type = cleaned.get('account_type')
        assigned_user = cleaned.get('assigned_user')
        if account_type == CashAccount.TYPE_SALES_REP_CASH:
            if not assigned_user:
                self.add_error('assigned_user', 'اختر المندوب لهذه العهدة المالية')
            elif assigned_user.role != User.ROLE_SALES:
                self.add_error('assigned_user', 'العهدة المالية تكون للمندوبين فقط')
        else:
            cleaned['assigned_user'] = None
        return cleaned


class ExpenseForm(forms.Form):
    cash_account = forms.ModelChoiceField(
        queryset=CashAccount.objects.filter(is_active=True),
        label='الخزنة التي سيتم الخصم منها',
        empty_label='اختر الخزنة',
    )
    amount = forms.DecimalField(min_value=0.01, label='المبلغ')
    transaction_date = forms.DateField(label='تاريخ المصروف', initial=timezone.localdate, widget=forms.DateInput(attrs={'type': 'date'}))
    notes = forms.CharField(widget=forms.Textarea, required=False, label='بيان المصروف')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['cash_account'].initial = CashAccount.get_cash_drawer()


class CustomerCollectionForm(forms.Form):
    cash_account = forms.ModelChoiceField(queryset=CashAccount.objects.filter(is_active=True), label='الخزنة')
    allowed_discount = forms.DecimalField(min_value=0, required=False, initial=0, label='خصم مسموح به')
    customer = forms.ModelChoiceField(queryset=Customer.objects.filter(is_active=True), label='العميل')
    order = forms.ModelChoiceField(
        queryset=Order.objects.exclude(
            status__in=[Order.STATUS_DRAFT, Order.STATUS_CANCELLED, Order.STATUS_RETURNED],
        ).exclude(document_type=Order.DOCUMENT_QUOTE),
        label='الطلب',
        required=False,
    )
    amount = forms.DecimalField(label='القبض', widget=forms.NumberInput(attrs={'step': '0.01'}))
    transaction_date = forms.DateTimeField(label='تاريخ ووقت التحصيل', initial=timezone.now, input_formats=['%Y-%m-%dT%H:%M'], widget=forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'}))
    notes = forms.CharField(widget=forms.Textarea, required=False, label='ملاحظات')

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        visible_customers = visible_customers_for_user(user, Customer.objects.filter(is_active=True))
        self.fields['customer'].queryset = visible_customers
        self.fields['order'].queryset = self.fields['order'].queryset.filter(customer__in=visible_customers)
        self.fields['cash_account'].initial = CashAccount.get_cash_drawer()
        self.fields['allowed_discount'].widget = forms.HiddenInput()
        self.fields['order'].widget = forms.HiddenInput()
        self.fields['notes'].widget = forms.HiddenInput()

    def clean(self):
        cleaned = super().clean()
        order = cleaned.get('order')
        customer = cleaned.get('customer')
        amount = cleaned.get('amount')
        allowed_discount = cleaned.get('allowed_discount') or 0
        if not customer:
            self.add_error('customer', 'اختر العميل')
        if amount is not None and amount == 0:
            self.add_error('amount', 'مبلغ القبض لا يمكن أن يساوي صفر')
        if order and not customer:
            cleaned['customer'] = order.customer
        return cleaned


class TransferForm(forms.Form):
    from_account = forms.ModelChoiceField(queryset=CashAccount.objects.filter(is_active=True), label='من خزنة')
    to_account = forms.ModelChoiceField(queryset=CashAccount.objects.filter(is_active=True), label='إلى خزنة')
    amount = forms.DecimalField(min_value=0.01, label='المبلغ')
    transaction_date = forms.DateField(label='تاريخ التحويل', initial=timezone.localdate, widget=forms.DateInput(attrs={'type': 'date'}))
    notes = forms.CharField(widget=forms.Textarea, required=False, label='ملاحظات')

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        main_account = CashAccount.get_default()
        CashAccount.get_cash_drawer()
        self.fields['to_account'].queryset = CashAccount.objects.filter(pk=main_account.pk)
        self.fields['to_account'].initial = main_account
        self.fields['to_account'].widget = forms.HiddenInput()
        if user and getattr(user, 'is_manager', False):
            self.fields['from_account'].queryset = CashAccount.objects.filter(is_active=True).exclude(pk=main_account.pk)
        elif user and getattr(user, 'role', None) == 'sales':
            rep_account = CashAccount.get_for_user(user)
            self.fields['from_account'].queryset = CashAccount.objects.filter(pk=rep_account.pk)
            self.fields['from_account'].initial = rep_account
        else:
            drawer = CashAccount.get_cash_drawer()
            self.fields['from_account'].queryset = CashAccount.objects.filter(pk=drawer.pk)
            self.fields['from_account'].initial = drawer


class SalesRepStatementForm(forms.Form):
    sales_rep = forms.ModelChoiceField(queryset=User.objects.filter(role=User.ROLE_SALES, is_active=True), label='المندوب')


class CashAccountStatementForm(forms.Form):
    cash_account = forms.ModelChoiceField(
        queryset=CashAccount.objects.all().order_by('account_type', 'name'),
        label='الخزنة',
        empty_label='اختر الخزنة',
    )


class SupplierPaymentForm(forms.Form):
    supplier = forms.ModelChoiceField(queryset=Supplier.objects.filter(is_active=True), label='المورد')
    cash_account = forms.ModelChoiceField(queryset=CashAccount.objects.filter(is_active=True), label='الخزنة')
    amount = forms.DecimalField(min_value=0.01, label='المبلغ')
    transaction_date = forms.DateField(label='تاريخ الدفع', initial=timezone.localdate, widget=forms.DateInput(attrs={'type': 'date'}))
    notes = forms.CharField(widget=forms.Textarea, required=False, label='ملاحظات')
