from django import forms

from accounts.models import User
from products.models import ProductVariant

from .models import Warehouse


class WarehouseForm(forms.ModelForm):
    class Meta:
        model = Warehouse
        fields = ('name', 'warehouse_type', 'assigned_user', 'address', 'is_active')
        labels = {
            'name': 'اسم المخزن',
            'warehouse_type': 'نوع المخزن',
            'assigned_user': 'المسؤول عن المخزن',
            'address': 'العنوان',
            'is_active': 'نشط',
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'اسم المخزن أو الفرع'}),
            'address': forms.Textarea(attrs={'placeholder': 'عنوان المخزن'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['warehouse_type'].choices = (
            (Warehouse.TYPE_MAIN, 'مخزن رئيسي'),
            (Warehouse.TYPE_STORE, 'مخزن فرعي'),
        )
        self.fields['assigned_user'].queryset = User.objects.filter(is_active=True).order_by('role', 'username')
        self.fields['assigned_user'].required = False


class StockMovementForm(forms.Form):
    variant = forms.ModelChoiceField(queryset=ProductVariant.objects.select_related('product', 'color', 'size'), label='المنتج')
    warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.filter(is_active=True), label='المخزن')
    quantity = forms.IntegerField(min_value=1, label='الكمية')
    note = forms.CharField(widget=forms.Textarea, required=False, label='ملاحظة')


class StockTransferForm(forms.Form):
    variant = forms.ModelChoiceField(queryset=ProductVariant.objects.select_related('product', 'color', 'size'), label='المنتج')
    from_warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.filter(is_active=True), label='من مخزن')
    to_warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.filter(is_active=True), label='إلى مخزن')
    quantity = forms.IntegerField(min_value=1, label='الكمية')
    note = forms.CharField(widget=forms.Textarea, required=False, label='ملاحظة')


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['variant'].widget.attrs.update({
            'data-stock-filter-target': 'id_from_warehouse',
            'data-stock-filter-scope': 'all',
        })


class RepresentativeIssueForm(forms.Form):
    representative = forms.ModelChoiceField(queryset=User.objects.filter(role=User.ROLE_SALES, is_active=True), label='المندوب')
    variant = forms.ModelChoiceField(queryset=ProductVariant.objects.select_related('product', 'color', 'size'), label='المنتج')
    from_warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.filter(is_active=True).exclude(warehouse_type=Warehouse.TYPE_REPRESENTATIVE), label='من مخزن')
    quantity = forms.IntegerField(min_value=1, label='الكمية')
    note = forms.CharField(widget=forms.Textarea, required=False, label='ملاحظة')


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['variant'].widget.attrs.update({
            'data-stock-filter-target': 'id_from_warehouse',
            'data-stock-filter-scope': 'non_representative',
        })


class RepresentativeReturnForm(forms.Form):
    representative = forms.ModelChoiceField(queryset=User.objects.filter(role=User.ROLE_SALES, is_active=True), label='المندوب')
    variant = forms.ModelChoiceField(queryset=ProductVariant.objects.select_related('product', 'color', 'size'), label='المنتج')
    to_warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.filter(is_active=True).exclude(warehouse_type=Warehouse.TYPE_REPRESENTATIVE), label='إلى مخزن')
    quantity = forms.IntegerField(min_value=1, label='الكمية المرتجعة')
    note = forms.CharField(widget=forms.Textarea, required=False, label='ملاحظة')


class StockAdjustmentForm(forms.Form):
    variant = forms.ModelChoiceField(queryset=ProductVariant.objects.select_related('product', 'color', 'size'), label='المنتج')
    warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.filter(is_active=True), label='المخزن')
    new_quantity = forms.IntegerField(min_value=0, label='الكمية الجديدة')
    note = forms.CharField(widget=forms.Textarea, required=False, label='سبب التسوية')


class TransferLineForm(forms.Form):
    variant = forms.ModelChoiceField(
        queryset=ProductVariant.objects.filter(is_active=True).select_related('product', 'color', 'size'),
        label='الصنف')
    quantity = forms.IntegerField(min_value=1, max_value=2147483647, label='الكمية')


TransferLineFormSet = forms.formset_factory(
    TransferLineForm, extra=3, min_num=1, validate_min=True,
    max_num=100, validate_max=True, absolute_max=100, can_delete=True)


class BulkStockTransferForm(forms.Form):
    from_warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.filter(is_active=True), label='من مخزن')
    to_warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.filter(is_active=True), label='إلى مخزن')
    note = forms.CharField(widget=forms.Textarea, required=False, label='ملاحظات')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lines = TransferLineFormSet(self.data if self.is_bound else None, prefix='items')

    def clean(self):
        data = super().clean()
        if not self.lines.is_valid():
            raise forms.ValidationError('راجع الأصناف والكميات في سطور التحويل.')
        if data.get('from_warehouse') == data.get('to_warehouse'):
            raise forms.ValidationError('لا يمكن التحويل إلى نفس المخزن.')
        data['items'] = [
            {'variant': row['variant'], 'quantity': row['quantity']}
            for row in self.lines.cleaned_data if row and not row.get('DELETE')
        ]
        return data
