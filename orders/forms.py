from django import forms
from django.core.exceptions import ValidationError

from inventory.models import Warehouse

from .models import Order


class OrderForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = (
            'order_type', 'customer', 'warehouse', 'payment_method',
            'wallet_from_number', 'wallet_to_number',
            'payment_status', 'paid_amount', 'discount_amount',
            'discount_percentage', 'discount_reason', 'notes',
        )
        labels = {
            'order_type': 'نوع الطلب',
            'customer': 'العميل',
            'warehouse': 'المخزن',
            'payment_method': 'طريقة الدفع',
            'wallet_from_number': 'رقم المحفظة المحول منها',
            'wallet_to_number': 'رقم المحفظة المحول إليها',
            'payment_status': 'حالة الدفع',
            'paid_amount': 'المبلغ المدفوع',
            'discount_amount': 'خصم عام بالقيمة',
            'discount_percentage': 'خصم عام بالنسبة',
            'discount_reason': 'سبب الخصم',
            'notes': 'ملاحظات',
        }
        widgets = {
            'wallet_from_number': forms.TextInput(attrs={'placeholder': 'رقم محفظة العميل'}),
            'wallet_to_number': forms.TextInput(attrs={'placeholder': 'رقم محفظة الشركة'}),
            'discount_reason': forms.Textarea(attrs={'placeholder': 'سبب الخصم ومن وافق عليه إن وجد', 'rows': 3}),
            'notes': forms.Textarea(attrs={'placeholder': 'أي ملاحظات خاصة بالطلب'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['customer'].required = False
        warehouses = Warehouse.objects.filter(is_active=True)
        if user and getattr(user, 'role', None) == 'sales' and not user.is_superuser:
            warehouses = warehouses.filter(assigned_user=user, warehouse_type=Warehouse.TYPE_REPRESENTATIVE)
        self.fields['warehouse'].queryset = warehouses

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
