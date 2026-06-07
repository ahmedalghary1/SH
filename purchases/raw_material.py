from django import forms
from django.core.exceptions import ValidationError

from finance.models import CashAccount, PaymentTransaction
from finance.services import record_transaction

from .models import Supplier


class RawMaterialPurchaseForm(forms.Form):
    operation_type = forms.CharField(initial='raw_material', widget=forms.HiddenInput)
    raw_name = forms.CharField(max_length=200, label='اسم الخام')
    supplier = forms.ModelChoiceField(queryset=Supplier.objects.filter(is_active=True), label='المورد')
    amount = forms.DecimalField(min_value=0.01, label='السعر')
    notes = forms.CharField(widget=forms.Textarea, required=False, label='ملاحظات')

    def clean_operation_type(self):
        value = self.cleaned_data['operation_type']
        if value != 'raw_material':
            raise forms.ValidationError('اختر شراء خام لتسجيل الحركة')
        return value


def record_raw_material_purchase(*, raw_name, supplier, amount, user, notes=''):
    if not raw_name:
        raise ValidationError('اسم الخام مطلوب')
    note = f'شراء خام: {raw_name}'
    if notes:
        note = f'{note} - {notes}'
    return record_transaction(
        transaction_type=PaymentTransaction.TYPE_SUPPLIER_PAYMENT,
        direction=PaymentTransaction.DIRECTION_OUT,
        amount=amount,
        cash_account=CashAccount.get_default(),
        related_supplier=supplier,
        related_supplier_name=str(supplier),
        notes=note,
        created_by=user,
    )
