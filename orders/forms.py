from django import forms
from django.core.exceptions import ValidationError

from inventory.models import Warehouse

from .models import Order


class OrderForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = (
            'document_type', 'order_type', 'customer', 'warehouse', 'payment_method',
            'wallet_from_number', 'wallet_to_number', 'discount_amount', 'discount_percentage',
        )
        labels = {
            'document_type': 'نوع المستند',
            'order_type': 'نوع الطلب',
            'customer': 'العميل',
            'warehouse': 'المخزن',
            'payment_method': 'طريقة الدفع',
            'wallet_from_number': 'رقم محفظة العميل',
            'wallet_to_number': 'رقم محفظة الشركة',
            'discount_amount': 'خصم عام بالقيمة',
            'discount_percentage': 'خصم عام بالنسبة',
        }
        widgets = {
            'warehouse': forms.HiddenInput(),
            'wallet_from_number': forms.TextInput(attrs={'placeholder': 'رقم محفظة العميل'}),
            'wallet_to_number': forms.TextInput(attrs={'placeholder': 'رقم محفظة الشركة'}),
            'discount_amount': forms.NumberInput(attrs={'min': '0', 'step': '0.01', 'placeholder': '0.00'}),
            'discount_percentage': forms.NumberInput(attrs={'min': '0', 'max': '100', 'step': '0.01', 'placeholder': '0'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['customer'].required = False
        self.fields['warehouse'].required = False
        # Set default document type to sale and hide it
        self.fields['document_type'].initial = self.initial.get('document_type', Order.DOCUMENT_SALE)
        self.fields['document_type'].widget = forms.HiddenInput()
        # Set default order type to b2c and hide it
        self.fields['order_type'].initial = self.initial.get('order_type', Order.TYPE_B2C)
        self.fields['order_type'].widget = forms.HiddenInput()
        # Hide discount percentage - use only discount amount
        self.fields['discount_percentage'].widget = forms.HiddenInput()
        self.fields['discount_percentage'].initial = 0
        # Hide wallet fields by default
        self.fields['wallet_from_number'].widget = forms.HiddenInput()
        self.fields['wallet_to_number'].widget = forms.HiddenInput()
        
        warehouses = Warehouse.objects.filter(is_active=True)
        if user and getattr(user, 'role', None) == 'sales' and not user.is_superuser:
            warehouses = warehouses.filter(assigned_user=user, warehouse_type=Warehouse.TYPE_REPRESENTATIVE)
        self.fields['warehouse'].queryset = warehouses
        self.fields['payment_method'].choices = (
            (Order.METHOD_CASH, 'نقدي'),
            (Order.METHOD_WALLET, 'تحويل عبر محفظة'),
            (Order.METHOD_CREDIT, 'آجل'),
        )
        self.fields['payment_method'].initial = Order.METHOD_CASH

    def clean(self):
        cleaned = super().clean()
        document_type = cleaned.get('document_type')
        order_type = cleaned.get('order_type')
        customer = cleaned.get('customer')
        payment_method = cleaned.get('payment_method')
        wallet_from = cleaned.get('wallet_from_number')
        wallet_to = cleaned.get('wallet_to_number')
        if order_type == Order.TYPE_B2B and not customer:
            raise ValidationError('بيانات العميل مطلوبة عند البيع لشركة أو تاجر')
        if document_type == Order.DOCUMENT_QUOTE:
            return cleaned
        if payment_method == Order.METHOD_CREDIT and not customer:
            raise ValidationError('اختر العميل عند تسجيل فاتورة آجلة')
        if payment_method == Order.METHOD_WALLET and (not wallet_from or not wallet_to):
            raise ValidationError('أرقام المحافظ مطلوبة عند اختيار الدفع بمحفظة')
        return cleaned
