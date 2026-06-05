from django import forms
from django.core.exceptions import ValidationError

from inventory.models import Warehouse

from .models import Order


class OrderForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = (
            'order_type', 'customer', 'warehouse', 'payment_method',
            'wallet_from_number', 'wallet_to_number', 'discount_percentage',
        )
        labels = {
            'order_type': 'نوع الطلب',
            'customer': 'العميل',
            'warehouse': 'المخزن',
            'payment_method': 'طريقة الدفع',
            'wallet_from_number': 'رقم محفظة العميل',
            'wallet_to_number': 'رقم محفظة الشركة',
            'discount_percentage': 'خصم عام بالنسبة',
        }
        widgets = {
            'warehouse': forms.HiddenInput(),
            'wallet_from_number': forms.TextInput(attrs={'placeholder': 'رقم محفظة العميل'}),
            'wallet_to_number': forms.TextInput(attrs={'placeholder': 'رقم محفظة الشركة'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['customer'].required = False
        self.fields['warehouse'].required = False
        warehouses = Warehouse.objects.filter(is_active=True)
        if user and getattr(user, 'role', None) == 'sales' and not user.is_superuser:
            warehouses = warehouses.filter(assigned_user=user, warehouse_type=Warehouse.TYPE_REPRESENTATIVE)
        self.fields['warehouse'].queryset = warehouses
        self.fields['payment_method'].choices = (
            (Order.METHOD_CASH, 'نقدي'),
            (Order.METHOD_WALLET, 'تحويل عبر محفظة'),
        )
        self.fields['payment_method'].initial = Order.METHOD_CASH

    def clean(self):
        cleaned = super().clean()
        order_type = cleaned.get('order_type')
        customer = cleaned.get('customer')
        payment_method = cleaned.get('payment_method')
        wallet_from = cleaned.get('wallet_from_number')
        wallet_to = cleaned.get('wallet_to_number')
        if order_type == Order.TYPE_B2B and not customer:
            raise ValidationError('بيانات العميل مطلوبة عند البيع لشركة أو تاجر')
        if payment_method == Order.METHOD_WALLET and (not wallet_from or not wallet_to):
            raise ValidationError('أرقام المحافظ مطلوبة عند اختيار الدفع بمحفظة')
        return cleaned
