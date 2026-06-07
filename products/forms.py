from django import forms

from inventory.models import Warehouse

from .models import Category, Color, Product, ProductVariant, Size


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ('name', 'is_active')
        labels = {
            'name': 'اسم التصنيف',
            'is_active': 'نشط',
        }


class ColorForm(forms.ModelForm):
    class Meta:
        model = Color
        fields = ('name', 'hex_code')
        labels = {
            'name': 'اسم اللون',
            'hex_code': 'كود اللون',
        }


class SizeForm(forms.ModelForm):
    class Meta:
        model = Size
        fields = ('name', 'sort_order')
        labels = {
            'name': 'اسم المقاس',
            'sort_order': 'ترتيب العرض',
        }


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ('name', 'sku', 'category', 'material', 'image')
        labels = {
            'name': 'اسم المنتج',
            'sku': 'كود المنتج',
            'category': 'التصنيف',
            'material': 'الخامة',
            'image': 'صورة المنتج',
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'اكتب اسم المنتج', 'list': 'product-name-options'}),
            'sku': forms.TextInput(attrs={'placeholder': 'مثال: 001'}),
            'category': forms.Select(attrs={'data-filterable-select': 'true'}),
            'material': forms.TextInput(attrs={'placeholder': 'مثال: قطن'}),
        }

    def save(self, commit=True):
        product = super().save(commit=False)
        product.retail_price = product.retail_price or 0
        product.wholesale_price = product.wholesale_price or 0
        if commit:
            product.save()
            self.save_m2m()
        return product


class ProductVariantForm(forms.ModelForm):
    class Meta:
        model = ProductVariant
        fields = ('product', 'color', 'size', 'cost_price', 'sale_price', 'is_active')
        labels = {
            'product': 'المنتج',
            'color': 'اللون',
            'size': 'المقاس',
            'cost_price': 'سعر الشراء',
            'sale_price': 'سعر البيع',
            'is_active': 'نشط',
        }
        widgets = {
            'cost_price': forms.NumberInput(attrs={'min': '0', 'step': '0.01', 'placeholder': 'اكتب سعر الشراء'}),
            'sale_price': forms.NumberInput(attrs={'min': '0', 'step': '0.01', 'placeholder': 'اكتب سعر البيع'}),
        }


class InitialProductVariantForm(forms.ModelForm):
    color = forms.ModelChoiceField(queryset=Color.objects.all().order_by('name'), label='اللون')
    size = forms.ModelChoiceField(queryset=Size.objects.all().order_by('sort_order', 'name'), label='المقاس')
    cost_price = forms.DecimalField(label='سعر الشراء', min_value=0)
    sale_price = forms.DecimalField(label='سعر البيع', min_value=0)

    class Meta:
        model = ProductVariant
        fields = ('color', 'size', 'cost_price', 'sale_price')
        widgets = {
            'color': forms.Select(attrs={'data-filterable-select': 'true'}),
            'size': forms.Select(attrs={'data-filterable-select': 'true'}),
            'cost_price': forms.NumberInput(attrs={'min': '0', 'step': '0.01', 'placeholder': 'سعر الشراء'}),
            'sale_price': forms.NumberInput(attrs={'min': '0', 'step': '0.01', 'placeholder': 'سعر البيع'}),
        }

    def has_variant_data(self):
        return self.is_valid()


class InitialStockForm(forms.Form):
    warehouse = forms.ModelChoiceField(
        queryset=Warehouse.objects.filter(is_active=True),
        label='المخزن',
        widget=forms.Select(attrs={'data-filterable-select': 'true'}),
    )
    quantity = forms.IntegerField(
        min_value=1,
        label='الكمية',
        initial=1,
    )

    def clean(self):
        cleaned = super().clean()
        warehouse = cleaned.get('warehouse')
        quantity = cleaned.get('quantity') or 0
        if quantity > 0 and not warehouse:
            self.add_error('warehouse', 'اختر المخزن')
        return cleaned

    def has_stock_data(self):
        return self.is_valid() and bool(self.cleaned_data.get('warehouse'))

