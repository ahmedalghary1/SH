from django import forms

from finance.models import CashAccount
from inventory.models import Warehouse
from products.models import ProductVariant

from .models import PurchaseOrder, Supplier


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ('name', 'phone', 'email', 'address', 'company_name', 'opening_balance', 'notes', 'is_active')
        labels = {
            'name': 'اسم المورد',
            'phone': 'الهاتف',
            'email': 'البريد الإلكتروني',
            'address': 'العنوان',
            'company_name': 'اسم الشركة',
            'opening_balance': 'الرصيد الافتتاحي',
            'notes': 'ملاحظات',
            'is_active': 'نشط',
        }


class PurchaseOrderForm(forms.Form):
    supplier = forms.ModelChoiceField(queryset=Supplier.objects.filter(is_active=True), label='المورد')
    status = forms.ChoiceField(
        choices=((PurchaseOrder.STATUS_DRAFT, 'مسودة'), (PurchaseOrder.STATUS_ORDERED, 'تم الطلب')),
        initial=PurchaseOrder.STATUS_ORDERED,
        label='الحالة',
    )
    order_date = forms.DateField(required=False, label='تاريخ الأمر', widget=forms.DateInput(attrs={'type': 'date'}))
    expected_date = forms.DateField(required=False, label='تاريخ متوقع للاستلام', widget=forms.DateInput(attrs={'type': 'date'}))
    product_variant = forms.ModelChoiceField(
        queryset=ProductVariant.objects.filter(is_active=True).select_related('product', 'color', 'size'),
        label='الصنف',
    )
    quantity = forms.IntegerField(min_value=1, label='الكمية')
    unit_cost = forms.DecimalField(min_value=0, label='تكلفة الوحدة')
    notes = forms.CharField(widget=forms.Textarea, required=False, label='ملاحظات')


class PurchaseReceiveForm(forms.Form):
    warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.filter(is_active=True), label='مخزن الاستلام')
    note = forms.CharField(widget=forms.Textarea, required=False, label='ملاحظة')

    def __init__(self, *args, purchase_order=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.purchase_order = purchase_order
        if purchase_order:
            for item in purchase_order.items.select_related('product_variant__product', 'product_variant__color', 'product_variant__size'):
                self.fields[f'item_{item.pk}'] = forms.IntegerField(
                    min_value=0,
                    max_value=item.remaining_quantity,
                    required=False,
                    initial=0,
                    label=f'{item.product_variant} - المتبقي {item.remaining_quantity}',
                )

    def received_items(self):
        data = {}
        for name, value in self.cleaned_data.items():
            if name.startswith('item_') and value:
                data[int(name.replace('item_', ''))] = value
        return data


class SupplierPaymentForm(forms.Form):
    cash_account = forms.ModelChoiceField(queryset=CashAccount.objects.filter(is_active=True), label='الخزنة')
    amount = forms.DecimalField(min_value=0.01, label='المبلغ')
    notes = forms.CharField(widget=forms.Textarea, required=False, label='ملاحظات الدفع')
