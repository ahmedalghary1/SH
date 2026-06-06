from django import forms
from django.db.models import Q

from orders.models import Order, OrderItem
from products.models import ProductVariant

from .models import SalesReturn, SalesReturnItem
from .services import calculate_available_return_quantity


class SalesReturnCreateForm(forms.Form):
    invoice_number = forms.CharField(
        label='رقم الفاتورة',
        widget=forms.TextInput(attrs={'placeholder': 'مثال: INV-20260606-0001'}),
    )
    return_type = forms.ChoiceField(choices=SalesReturn.RETURN_TYPE_CHOICES, label='نوع المرتجع')
    reason = forms.CharField(widget=forms.Textarea, required=False, label='سبب المرتجع')

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.order = None

    def clean_invoice_number(self):
        value = (self.cleaned_data.get('invoice_number') or '').strip()
        if not value:
            raise forms.ValidationError('أدخل رقم الفاتورة')

        orders = Order.objects.select_related('customer', 'warehouse', 'created_by').prefetch_related(
            'items__warehouse',
            'items__variant__product',
            'items__variant__color',
            'items__variant__size',
        ).filter(Q(invoice__invoice_number__iexact=value) | Q(order_number__iexact=value)).distinct()
        if self.user and getattr(self.user, 'role', None) == 'sales' and not self.user.is_superuser:
            orders = orders.filter(created_by=self.user)

        self.order = orders.first()
        if not self.order:
            raise forms.ValidationError('لم يتم العثور على فاتورة بهذا الرقم')
        if self.order.status in {Order.STATUS_DRAFT, Order.STATUS_CANCELLED, Order.STATUS_RETURNED}:
            raise forms.ValidationError('لا يمكن إنشاء مرتجع لهذه الفاتورة في حالتها الحالية')
        if not any(item.variant_id and calculate_available_return_quantity(item) > 0 for item in self.order.items.all()):
            raise forms.ValidationError('لا توجد كميات متاحة للإرجاع في هذه الفاتورة')
        return value


class ReturnItemForm(forms.Form):
    original_order_item = forms.ModelChoiceField(queryset=OrderItem.objects.none(), label='الصنف المرتجع')
    quantity = forms.IntegerField(min_value=1, label='الكمية')
    condition = forms.ChoiceField(choices=SalesReturnItem.CONDITION_CHOICES, label='حالة القطعة')
    return_to_stock = forms.BooleanField(required=False, initial=True, label='تعود للمخزون')
    notes = forms.CharField(widget=forms.Textarea, required=False, label='ملاحظات')

    def __init__(self, *args, sales_return=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.sales_return = sales_return
        if sales_return:
            self.fields['original_order_item'].queryset = sales_return.order.items.select_related('variant__product', 'variant__color', 'variant__size')

    def clean(self):
        cleaned = super().clean()
        item = cleaned.get('original_order_item')
        quantity = cleaned.get('quantity')
        if item and quantity and quantity > calculate_available_return_quantity(item):
            self.add_error('quantity', 'الكمية أكبر من المتاح للإرجاع')
        return cleaned


class ExchangeItemForm(forms.Form):
    old_order_item = forms.ModelChoiceField(queryset=OrderItem.objects.none(), label='الصنف القديم')
    new_product_variant = forms.ModelChoiceField(
        queryset=ProductVariant.objects.filter(is_active=True).select_related('product', 'color', 'size'),
        label='الصنف الجديد',
    )
    quantity = forms.IntegerField(min_value=1, label='الكمية')
    new_unit_price = forms.DecimalField(min_value=0, label='سعر الصنف الجديد')
    notes = forms.CharField(widget=forms.Textarea, required=False, label='ملاحظات')

    def __init__(self, *args, sales_return=None, **kwargs):
        super().__init__(*args, **kwargs)
        if sales_return:
            self.fields['old_order_item'].queryset = sales_return.order.items.select_related('variant__product', 'variant__color', 'variant__size')


class CompleteReturnForm(forms.Form):
    pass
