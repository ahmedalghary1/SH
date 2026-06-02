from django import forms

from .models import Category, Color, Product, ProductVariant, Size


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ('name', 'parent', 'is_active')


class ColorForm(forms.ModelForm):
    class Meta:
        model = Color
        fields = ('name', 'hex_code')


class SizeForm(forms.ModelForm):
    class Meta:
        model = Size
        fields = ('name', 'sort_order')


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = (
            'name', 'sku', 'category', 'description', 'material', 'season',
            'retail_price', 'wholesale_price', 'image', 'is_active',
        )


class ProductVariantForm(forms.ModelForm):
    class Meta:
        model = ProductVariant
        fields = ('product', 'color', 'size', 'variant_sku', 'barcode', 'is_active')
