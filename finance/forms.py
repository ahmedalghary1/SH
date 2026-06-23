from django import forms
from django.utils import timezone

from accounts.models import User
from customers.models import Customer
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

    def clean(self):
        cleaned = super().clean()
        return cleaned


class ExpenseForm(forms.Form):
    amount = forms.DecimalField(min_value=0.01, label='المبلغ')
    transaction_date = forms.DateField(label='تاريخ المصروف', initial=timezone.localdate, widget=forms.DateInput(attrs={'type': 'date'}))
    notes = forms.CharField(widget=forms.Textarea, required=False, label='بيان المصروف')


class CustomerCollectionForm(forms.Form):
    cash_account = forms.ModelChoiceField(queryset=CashAccount.objects.filter(is_active=True), label='الخزنة', required=False)
    allowed_discount = forms.DecimalField(min_value=0, required=False, initial=0, label='خصم مسموح به')
    customer = forms.ModelChoiceField(queryset=Customer.objects.filter(is_active=True), label='العميل', required=False)
    order = forms.ModelChoiceField(queryset=Order.objects.exclude(remaining_amount=0), label='الطلب', required=False)
    amount = forms.DecimalField(label='المبلغ')
    transaction_date = forms.DateField(label='تاريخ التحصيل', initial=timezone.localdate, widget=forms.DateInput(attrs={'type': 'date'}))
    notes = forms.CharField(widget=forms.Textarea, required=False, label='ملاحظات')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['cash_account'].initial = CashAccount.get_cash_drawer()

    def clean(self):
        cleaned = super().clean()
        order = cleaned.get('order')
        customer = cleaned.get('customer')
        amount = cleaned.get('amount')
        allowed_discount = cleaned.get('allowed_discount') or 0
        if not order and not customer:
            raise forms.ValidationError('اختر طلبًا أو عميلًا لتسجيل التحصيل')
        if amount == 0:
            self.add_error('amount', 'المبلغ لا يمكن أن يساوي صفر')
        if order and amount and amount <= 0:
            self.add_error('amount', 'تحصيل الفاتورة يجب أن يكون مبلغًا موجبًا')
        if order and amount and allowed_discount and amount + allowed_discount <= 0:
            self.add_error('amount', 'إجمالي التحصيل والخصم يجب أن يكون موجبًا')
        if order and amount and amount + allowed_discount > order.remaining_amount:
            self.add_error('amount', 'مبلغ التحصيل أكبر من المتبقي على الطلب')
        if order and not customer:
            cleaned['customer'] = order.customer
        return cleaned


class TransferForm(forms.Form):
    from_account = forms.ModelChoiceField(queryset=CashAccount.objects.filter(is_active=True), label='من خزنة')
    to_account = forms.ModelChoiceField(queryset=CashAccount.objects.filter(is_active=True), label='إلى خزنة')
    amount = forms.DecimalField(min_value=0.01, label='المبلغ')
    transaction_date = forms.DateField(label='تاريخ التحويل', initial=timezone.localdate, widget=forms.DateInput(attrs={'type': 'date'}))
    notes = forms.CharField(widget=forms.Textarea, required=False, label='ملاحظات')


class SalesRepStatementForm(forms.Form):
    sales_rep = forms.ModelChoiceField(queryset=User.objects.filter(role=User.ROLE_SALES, is_active=True), label='المندوب')


class SupplierPaymentForm(forms.Form):
    supplier = forms.ModelChoiceField(queryset=Supplier.objects.filter(is_active=True), label='المورد')
    amount = forms.DecimalField(min_value=0.01, label='المبلغ')
    transaction_date = forms.DateField(label='تاريخ الدفع', initial=timezone.localdate, widget=forms.DateInput(attrs={'type': 'date'}))
    notes = forms.CharField(widget=forms.Textarea, required=False, label='ملاحظات')
