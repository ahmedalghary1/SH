from django import forms

from products.models import ProductVariant

from .models import Warehouse


class WarehouseForm(forms.ModelForm):
    class Meta:
        model = Warehouse
        fields = ('name', 'warehouse_type', 'address', 'is_active')


class StockMovementForm(forms.Form):
    variant = forms.ModelChoiceField(queryset=ProductVariant.objects.select_related('product', 'color', 'size'), label='المتغير')
    warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.filter(is_active=True), label='المخزن')
    quantity = forms.IntegerField(min_value=1, label='الكمية')
    note = forms.CharField(widget=forms.Textarea, required=False, label='ملاحظة')


class StockTransferForm(forms.Form):
    variant = forms.ModelChoiceField(queryset=ProductVariant.objects.select_related('product', 'color', 'size'), label='المتغير')
    from_warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.filter(is_active=True), label='من مخزن')
    to_warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.filter(is_active=True), label='إلى مخزن')
    quantity = forms.IntegerField(min_value=1, label='الكمية')
    note = forms.CharField(widget=forms.Textarea, required=False, label='ملاحظة')


class StockAdjustmentForm(forms.Form):
    variant = forms.ModelChoiceField(queryset=ProductVariant.objects.select_related('product', 'color', 'size'), label='المتغير')
    warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.filter(is_active=True), label='المخزن')
    new_quantity = forms.IntegerField(min_value=0, label='الكمية الجديدة')
    note = forms.CharField(widget=forms.Textarea, required=False, label='سبب التسوية')
