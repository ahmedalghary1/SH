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


class RepresentativeIssueForm(forms.Form):
    representative = forms.ModelChoiceField(queryset=User.objects.filter(role=User.ROLE_SALES, is_active=True), label='المندوب')
    variant = forms.ModelChoiceField(queryset=ProductVariant.objects.select_related('product', 'color', 'size'), label='المنتج')
    from_warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.filter(is_active=True).exclude(warehouse_type=Warehouse.TYPE_REPRESENTATIVE), label='من مخزن')
    quantity = forms.IntegerField(min_value=1, label='الكمية')
    note = forms.CharField(widget=forms.Textarea, required=False, label='ملاحظة')


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
