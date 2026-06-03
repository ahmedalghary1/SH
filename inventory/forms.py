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
            'assigned_user': 'المندوب المسؤول',
            'address': 'العنوان',
            'is_active': 'نشط',
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'اسم المخزن أو الفرع'}),
            'address': forms.Textarea(attrs={'placeholder': 'عنوان المخزن'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['assigned_user'].queryset = User.objects.filter(role=User.ROLE_SALES, is_active=True)
        self.fields['assigned_user'].required = False

    def clean(self):
        cleaned = super().clean()
        warehouse_type = cleaned.get('warehouse_type')
        assigned_user = cleaned.get('assigned_user')
        if warehouse_type == Warehouse.TYPE_REPRESENTATIVE and not assigned_user:
            self.add_error('assigned_user', 'اختر المندوب عند إنشاء عهدة مندوب')
        if warehouse_type != Warehouse.TYPE_REPRESENTATIVE and assigned_user:
            self.add_error('assigned_user', 'ربط المندوب متاح فقط مع نوع عهدة مندوب')
        return cleaned


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
    variant = forms.ModelChoiceField(queryset=ProductVariant.objects.select_related('product', 'color', 'size'), label='المتغير')
    warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.filter(is_active=True), label='المخزن')
    new_quantity = forms.IntegerField(min_value=0, label='الكمية الجديدة')
    note = forms.CharField(widget=forms.Textarea, required=False, label='سبب التسوية')
