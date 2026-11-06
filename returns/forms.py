from django import forms

from django.db.models import Q
from django.utils import timezone

from orders.models import Order, OrderItem
from products.models import ProductVariant
from customers.models import Customer

from .models import SalesReturn, SalesReturnItem
from .services import calculate_available_return_quantity


class ReturnDateTimeForm(forms.Form):
    return_datetime = forms.DateTimeField(
        required=False,
        label='تاريخ ووقت المرتجع',
        initial=timezone.now,
        input_formats=['%Y-%m-%dT%H:%M'],
        widget=forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Invoice/customer searches bind the form before the date is entered.
        if self.is_bound and 'return_datetime' not in self.data:
            self.data = self.data.copy()
            self.data['return_datetime'] = timezone.localtime().strftime('%Y-%m-%dT%H:%M')


class CustomerReturnCreateForm(ReturnDateTimeForm):
    customer = forms.ModelChoiceField(queryset=Customer.objects.none(), label='حساب العميل')
    reason = forms.CharField(required=False, label='سبب المرتجع')

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        customers = Customer.objects.all()
        if user.role == 'sales' and not user.is_superuser:
            customers = customers.filter(order__created_by=user).distinct()
        self.fields['customer'].queryset = customers.order_by('name', 'pk')


class SalesReturnCreateForm(ReturnDateTimeForm):
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
        ).filter(
            Q(order_number__iexact=value) | Q(invoice__invoice_number__iexact=value)
        ).distinct()
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
