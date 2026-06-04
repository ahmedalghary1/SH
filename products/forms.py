from django import forms

from inventory.models import Warehouse

from .models import Category, Color, Product, ProductVariant, Size


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ('name', 'parent', 'is_active')
        labels = {
            'name': 'اسم التصنيف',
            'parent': 'التصنيف الأب',
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
        fields = (
            'name', 'sku', 'category', 'description', 'material', 'season',
            'retail_price', 'wholesale_price', 'image', 'is_active',
        )
        labels = {
            'name': 'اسم المنتج',
            'sku': 'كود المنتج',
            'category': 'التصنيف',
            'description': 'الوصف',
            'material': 'الخامة',
            'season': 'الموسم',
            'retail_price': 'سعر القطاعي',
            'wholesale_price': 'سعر الجملة',
            'image': 'صورة المنتج',
            'is_active': 'نشط',
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'اسم واضح للمنتج'}),
            'sku': forms.TextInput(attrs={'placeholder': 'مثال: 001'}),
            'description': forms.Textarea(attrs={'placeholder': 'تفاصيل مختصرة عن المنتج'}),
            'material': forms.TextInput(attrs={'placeholder': 'قطن، بوليستر...'}),
            'season': forms.TextInput(attrs={'placeholder': 'صيفي، شتوي، طوال العام'}),
        }


class ProductVariantForm(forms.ModelForm):
    class Meta:
        model = ProductVariant
        fields = ('product', 'color', 'size', 'variant_sku', 'barcode', 'cost_price', 'is_active')
        labels = {
            'product': 'المنتج',
            'color': 'اللون',
            'size': 'المقاس',
            'variant_sku': 'كود المتغير',
            'barcode': 'الباركود',
            'cost_price': 'تكلفة القطعة',
            'is_active': 'نشط',
        }


class InitialProductVariantForm(forms.ModelForm):
    color = forms.ModelChoiceField(queryset=Color.objects.all(), label='اللون', required=False)
    new_color_name = forms.CharField(label='لون جديد', required=False)
    size = forms.ModelChoiceField(queryset=Size.objects.all(), label='المقاس', required=False)
    new_size_name = forms.CharField(label='مقاس جديد', required=False)
    variant_sku = forms.CharField(label='كود المتغير', required=False)
    barcode = forms.CharField(label='الباركود', required=False)
    cost_price = forms.DecimalField(label='تكلفة القطعة', min_value=0, required=False, initial=0)

    class Meta:
        model = ProductVariant
        fields = ('color', 'new_color_name', 'size', 'new_size_name', 'variant_sku', 'barcode', 'cost_price')
        widgets = {
            'new_color_name': forms.TextInput(attrs={'placeholder': 'اكتب لونًا جديدًا'}),
            'new_size_name': forms.TextInput(attrs={'placeholder': 'اكتب مقاسًا جديدًا'}),
            'variant_sku': forms.TextInput(attrs={'placeholder': 'اتركه فارغًا للتوليد التلقائي'}),
            'barcode': forms.TextInput(attrs={'placeholder': 'الباركود إن وجد'}),
        }

    def has_variant_data(self):
        if not self.is_valid():
            return False
        return any(
            self.cleaned_data.get(field)
            for field in ('color', 'new_color_name', 'size', 'new_size_name', 'variant_sku', 'barcode', 'cost_price')
        )


class InitialStockForm(forms.Form):
    warehouse = forms.ModelChoiceField(
        queryset=Warehouse.objects.filter(is_active=True),
        label='المخزن',
        required=False,
    )
    quantity = forms.IntegerField(
        min_value=0,
        label='الكمية الأولية',
        required=False,
        initial=0,
    )
    min_quantity = forms.IntegerField(
        min_value=0,
        label='حد التنبيه الأدنى',
        required=False,
        initial=0,
    )

    def clean(self):
        cleaned = super().clean()
        warehouse = cleaned.get('warehouse')
        quantity = cleaned.get('quantity') or 0
        min_quantity = cleaned.get('min_quantity') or 0
        if (quantity > 0 or min_quantity > 0) and not warehouse:
            self.add_error('warehouse', 'اختر المخزن لإضافة الكمية')
        return cleaned

    def has_stock_data(self):
        if not self.is_valid():
            return False
        return bool(self.cleaned_data.get('warehouse'))
