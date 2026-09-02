from django import forms

from inventory.models import Warehouse
from .models import Category, Color, Product, ProductVariant, Size
from config.branching import branch_context_is_set, get_current_branch_id


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


    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        branch_id = self.instance.branch_id or get_current_branch_id()
        duplicate = Color.all_objects.filter(branch_id=branch_id, name=name).exclude(pk=self.instance.pk)
        if branch_id and duplicate.exists():
            raise forms.ValidationError('هذا اللون موجود بالفعل في المعرض.')
        return name


class SizeForm(forms.ModelForm):
    class Meta:
        model = Size
        fields = ('name', 'sort_order')
        labels = {
            'name': 'اسم المقاس',
            'sort_order': 'ترتيب العرض',
        }


    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        branch_id = self.instance.branch_id or get_current_branch_id()
        duplicate = Size.all_objects.filter(branch_id=branch_id, name=name).exclude(pk=self.instance.pk)
        if branch_id and duplicate.exists():
            raise forms.ValidationError('هذا المقاس موجود بالفعل في المعرض.')
        return name


class ProductForm(forms.ModelForm):
    new_category_name = forms.CharField(required=False, max_length=100, label='تصنيف جديد')

    class Meta:
        model = Product
        fields = ('name', 'sku', 'category', 'material', 'season', 'pieces_per_dozen', 'image')
        labels = {
            'name': 'اسم المنتج',
            'sku': 'كود المنتج',
            'category': 'التصنيف',
            'material': 'الخامة',
            'season': 'السنة',
            'pieces_per_dozen': 'عدد القطع في الدستة',
            'image': 'صورة المنتج',
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'اكتب اسم المنتج', 'list': 'product-name-options'}),
            'sku': forms.TextInput(attrs={'placeholder': 'مثال: 001'}),
            'category': forms.Select(attrs={'data-filterable-select': 'true'}),
            'material': forms.TextInput(attrs={'placeholder': 'مثال: قطن'}),
            'season': forms.TextInput(attrs={'placeholder': 'مثال: 2026'}),
            'pieces_per_dozen': forms.NumberInput(attrs={'min': '1', 'step': '1', 'placeholder': '12'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].required = False

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('category') and not (cleaned.get('new_category_name') or '').strip():
            self.add_error('category', 'اختر التصنيف أو اكتب تصنيف جديد')
        return cleaned

    def clean_sku(self):
        sku = self.cleaned_data['sku'].strip()
        branch_id = self.instance.branch_id or get_current_branch_id()
        if not branch_id and not branch_context_is_set():
            from config.branching import get_default_branch_id
            branch_id = get_default_branch_id()
        duplicate = Product.all_objects.filter(branch_id=branch_id, sku=sku).exclude(pk=self.instance.pk)
        if branch_id and duplicate.exists():
            raise forms.ValidationError('كود المنتج موجود بالفعل في هذا المعرض.')
        return sku

    def save(self, commit=True):
        product = super().save(commit=False)
        new_category_name = (self.cleaned_data.get('new_category_name') or '').strip()
        if not product.category_id and new_category_name:
            # Category names were historically allowed to repeat.  Using
            # get_or_create() here raises MultipleObjectsReturned when such
            # data exists, which turns product creation into a server error.
            product.category = (
                Category.objects.filter(name=new_category_name).order_by('pk').first()
                or Category.objects.create(name=new_category_name, is_active=True)
            )
        product.retail_price = product.retail_price or 0
        product.wholesale_price = product.wholesale_price or 0
        if commit:
            product.save()
            self.save_m2m()
        return product


class ProductImportForm(forms.Form):
    product_file = forms.FileField(
        label='ملف Excel',
        help_text='الملفات المدعومة: XLSX و XLSM، بحد أقصى 5 ميجابايت.',
        widget=forms.ClearableFileInput(attrs={'accept': '.xlsx,.xlsm'}),
    )

    def clean_product_file(self):
        product_file = self.cleaned_data['product_file']
        extension = product_file.name.rsplit('.', 1)[-1].lower() if '.' in product_file.name else ''
        if extension not in {'xlsx', 'xlsm'}:
            raise forms.ValidationError('اختر ملف Excel بصيغة XLSX أو XLSM.')
        if product_file.size > 5 * 1024 * 1024:
            raise forms.ValidationError('حجم الملف أكبر من الحد المسموح (5 ميجابايت).')
        return product_file


class ProductVariantForm(forms.ModelForm):
    class Meta:
        model = ProductVariant
        fields = ('product', 'color', 'size', 'image', 'cost_price', 'retail_price', 'wholesale_price', 'is_active')
        labels = {
            'product': 'المنتج',
            'color': 'اللون',
            'size': 'المقاس',
            'image': 'صورة اللون / المقاس',
            'cost_price': 'سعر الشراء',
            'retail_price': 'سعر القطاعي',
            'wholesale_price': 'سعر الجملة',
            'is_active': 'نشط',
        }
        widgets = {
            'cost_price': forms.NumberInput(attrs={'min': '0', 'step': '0.01', 'placeholder': 'اكتب سعر الشراء'}),
            'retail_price': forms.NumberInput(attrs={'min': '0', 'step': '0.01', 'placeholder': 'سعر القطاعي'}),
            'wholesale_price': forms.NumberInput(attrs={'min': '0', 'step': '0.01', 'placeholder': 'سعر الجملة'}),
        }


class InitialProductVariantForm(forms.ModelForm):
    color = forms.ModelChoiceField(queryset=Color.objects.all().order_by('name'), label='اللون', required=False)
    new_color_name = forms.CharField(required=False, max_length=50, label='لون جديد')
    size = forms.ModelChoiceField(queryset=Size.objects.all().order_by('sort_order', 'name'), label='المقاس', required=False)
    new_size_name = forms.CharField(required=False, max_length=20, label='مقاس جديد')
    image = forms.ImageField(label='صورة اللون / المقاس', required=False)
    cost_price = forms.DecimalField(label='سعر الشراء', min_value=0)
    retail_price = forms.DecimalField(label='سعر القطاعي', min_value=0)
    wholesale_price = forms.DecimalField(label='سعر الجملة', min_value=0)

    class Meta:
        model = ProductVariant
        fields = ('color', 'size', 'image', 'cost_price', 'retail_price', 'wholesale_price')
        widgets = {
            'color': forms.Select(attrs={'data-filterable-select': 'true'}),
            'size': forms.Select(attrs={'data-filterable-select': 'true'}),
            'cost_price': forms.NumberInput(attrs={'min': '0', 'step': '0.01', 'placeholder': 'سعر الشراء'}),
            'retail_price': forms.NumberInput(attrs={'min': '0', 'step': '0.01', 'placeholder': 'سعر القطاعي'}),
            'wholesale_price': forms.NumberInput(attrs={'min': '0', 'step': '0.01', 'placeholder': 'سعر الجملة'}),
        }

    def has_variant_data(self):
        return self.is_valid()

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('color') and not (cleaned.get('new_color_name') or '').strip():
            self.add_error('color', 'اختر اللون أو اكتب لون جديد')
        if not cleaned.get('size') and not (cleaned.get('new_size_name') or '').strip():
            self.add_error('size', 'اختر المقاس أو اكتب مقاس جديد')
        return cleaned


class InitialStockForm(forms.Form):
    warehouse = forms.ModelChoiceField(
        queryset=Warehouse.objects.filter(is_active=True),
        label='المخزن',
        widget=forms.Select(attrs={'data-filterable-select': 'true'}),
        required=False,
    )
    new_warehouse_name = forms.CharField(required=False, max_length=100, label='مخزن جديد')
    quantity = forms.IntegerField(
        min_value=0,
        label='الرصيد الافتتاحي',
        initial=0,
        required=False,
        widget=forms.NumberInput(attrs={'min': '0', 'step': '1'}),
    )

    def clean(self):
        cleaned = super().clean()
        warehouse = cleaned.get('warehouse')
        new_warehouse_name = (cleaned.get('new_warehouse_name') or '').strip()
        quantity = cleaned.get('quantity') or 0
        if quantity > 0 and not warehouse and not new_warehouse_name:
            self.add_error('warehouse', 'اختر المخزن')
        return cleaned

    def has_stock_data(self):
        return self.is_valid() and bool(
            self.cleaned_data.get('warehouse') or (self.cleaned_data.get('new_warehouse_name') or '').strip()
        )
