from django import forms
from django.db.models import Q

from finance.models import CashAccount
from inventory.models import Stock, Warehouse
from products.models import Category, Color, Product, ProductVariant, Size

from .models import PurchaseOrder, Supplier


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ('name', 'phone', 'email', 'address', 'company_name', 'notes')
        labels = {
            'name': 'اسم المورد',
            'phone': 'الهاتف',
            'email': 'البريد الإلكتروني',
            'address': 'العنوان',
            'company_name': 'اسم الشركة',
            'notes': 'ملاحظات',
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'اسم المورد'}),
            'phone': forms.TextInput(attrs={'placeholder': 'رقم الهاتف'}),
            'address': forms.Textarea(attrs={'placeholder': 'عنوان المورد', 'rows': 3}),
            'notes': forms.Textarea(attrs={'placeholder': 'ملاحظات', 'rows': 3}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user


class SimpleSupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ('name', 'phone', 'email', 'address', 'company_name', 'notes')
        labels = {
            'name': 'اسم المورد',
            'phone': 'الهاتف',
            'email': 'البريد الإلكتروني',
            'address': 'العنوان',
            'company_name': 'اسم الشركة',
            'notes': 'ملاحظات',
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'اسم المورد'}),
            'phone': forms.TextInput(attrs={'placeholder': 'رقم الهاتف'}),
            'address': forms.Textarea(attrs={'placeholder': 'عنوان المورد', 'rows': 3}),
            'notes': forms.Textarea(attrs={'placeholder': 'ملاحظات', 'rows': 3}),
        }


class PurchaseOrderForm(forms.Form):
    supplier = forms.ModelChoiceField(queryset=Supplier.objects.filter(is_active=True), label='المورد', required=False)
    new_supplier_name = forms.CharField(required=False, label='مورد جديد')
    new_supplier_phone = forms.CharField(required=False, label='هاتف المورد')
    status = forms.ChoiceField(
        choices=((PurchaseOrder.STATUS_DRAFT, 'مسودة'), (PurchaseOrder.STATUS_ORDERED, 'تم الطلب')),
        initial=PurchaseOrder.STATUS_ORDERED,
        label='الحالة',
        required=False,
    )
    order_date = forms.DateField(required=False, label='تاريخ الأمر', widget=forms.DateInput(attrs={'type': 'date'}))
    expected_date = forms.DateField(required=False, label='تاريخ متوقع للاستلام', widget=forms.DateInput(attrs={'type': 'date'}))
    product_variant = forms.ModelChoiceField(
        queryset=ProductVariant.objects.filter(is_active=True).select_related('product', 'color', 'size'),
        label='المنتج',
        required=False,
    )
    new_product_name = forms.CharField(required=False, label='منتج جديد')
    new_product_sku = forms.CharField(required=False, label='كود المنتج الجديد')
    new_category = forms.ModelChoiceField(queryset=Category.objects.filter(is_active=True), required=False, label='تصنيف المنتج الجديد')
    new_category_name = forms.CharField(required=False, label='تصنيف جديد')
    new_color = forms.ModelChoiceField(queryset=Color.objects.all().order_by('name'), required=False, label='لون المنتج الجديد')
    new_color_name = forms.CharField(required=False, label='لون جديد')
    new_size = forms.ModelChoiceField(queryset=Size.objects.all().order_by('sort_order', 'name'), required=False, label='مقاس المنتج الجديد')
    new_size_name = forms.CharField(required=False, label='مقاس جديد')
    pieces_per_dozen = forms.IntegerField(min_value=1, required=False, initial=12, label='عدد القطع في الدستة')
    retail_price = forms.DecimalField(min_value=0, required=False, label='سعر قطاعي')
    wholesale_price = forms.DecimalField(min_value=0, required=False, label='سعر جملة')
    warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.filter(is_active=True), label='مخزن الإضافة', required=False)
    cash_account = forms.ModelChoiceField(queryset=CashAccount.objects.filter(is_active=True), label='الخزنة')
    quantity = forms.IntegerField(min_value=1, label='الكمية')
    unit_cost = forms.DecimalField(min_value=0, label='سعر الشراء')
    notes = forms.CharField(widget=forms.Textarea, required=False, label='ملاحظات')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['status'].initial = PurchaseOrder.STATUS_ORDERED
        self.fields['cash_account'].initial = CashAccount.get_cash_drawer()

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('supplier') and not (cleaned.get('new_supplier_name') or '').strip():
            self.add_error('supplier', 'اختر المورد أو أضف مورد جديد')
        if not cleaned.get('warehouse'):
            self.add_error('warehouse', 'اختر المخزن')
        if cleaned.get('product_variant'):
            return cleaned
        if not (cleaned.get('new_product_name') or '').strip():
            self.add_error('product_variant', 'اختر الصنف أو اكتب منتج جديد')
        if not (cleaned.get('new_product_sku') or '').strip():
            self.add_error('new_product_sku', 'اكتب كود المنتج الجديد')
        elif Product.objects.filter(sku=(cleaned.get('new_product_sku') or '').strip()).exists():
            self.add_error('new_product_sku', 'كود المنتج موجود بالفعل')
        if not cleaned.get('new_category') and not (cleaned.get('new_category_name') or '').strip():
            self.add_error('new_category', 'اختر التصنيف أو اكتب تصنيف جديد')
        if not cleaned.get('new_color') and not (cleaned.get('new_color_name') or '').strip():
            self.add_error('new_color', 'اختر اللون أو اكتب لون جديد')
        if not cleaned.get('new_size') and not (cleaned.get('new_size_name') or '').strip():
            self.add_error('new_size', 'اختر المقاس أو اكتب مقاس جديد')
        return cleaned


class PurchaseReceiveForm(forms.Form):
    warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.filter(is_active=True), label='مخزن الاستلام')
    note = forms.CharField(widget=forms.Textarea, required=False, label='ملاحظة')

    def __init__(self, *args, purchase_order=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.purchase_order = purchase_order
        if purchase_order:
            for item in purchase_order.items.select_related('product_variant__product', 'product_variant__color', 'product_variant__size'):
                self.fields[f'item_{item.pk}'] = forms.IntegerField(
                    min_value=0,
                    max_value=item.remaining_quantity,
                    required=False,
                    initial=0,
                    label=f'{item.product_variant} - المتبقي {item.remaining_quantity}',
                )

    def received_items(self):
        data = {}
        for name, value in self.cleaned_data.items():
            if name.startswith('item_') and value:
                data[int(name.replace('item_', ''))] = value
        return data


class SupplierPaymentForm(forms.Form):
    cash_account = forms.ModelChoiceField(queryset=CashAccount.objects.filter(is_active=True), label='الخزنة')
    amount = forms.DecimalField(min_value=0.01, label='المبلغ')
    notes = forms.CharField(widget=forms.Textarea, required=False, label='ملاحظات الدفع')


class PurchaseReturnForm(forms.Form):
    supplier = forms.ModelChoiceField(queryset=Supplier.objects.filter(is_active=True), label='المورد')
    product_variant = forms.ModelChoiceField(
        queryset=ProductVariant.objects.filter(is_active=True).select_related('product', 'color', 'size'),
        label='الصنف',
    )
    warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.filter(is_active=True), label='المخزن')
    quantity = forms.IntegerField(min_value=1, label='الكمية')
    unit_cost = forms.DecimalField(min_value=0, label='تكلفة الوحدة')
    notes = forms.CharField(widget=forms.Textarea, required=False, label='ملاحظات')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        supplier_id = self.data.get('supplier') if self.is_bound else self.initial.get('supplier')
        self.fields['supplier'].widget.attrs.update({'data-purchase-return-supplier': 'true'})
        self.fields['product_variant'].widget.attrs.update({'data-purchase-return-variant': 'true'})
        self.fields['warehouse'].widget.attrs.update({'data-purchase-return-warehouse': 'true'})
        if supplier_id:
            product_variant_id = self.data.get('product_variant') if self.is_bound else self.initial.get('product_variant')
            variant_filter = Q(product__supplier_id=supplier_id)
            if product_variant_id:
                variant_filter |= Q(pk=product_variant_id)
            self.fields['product_variant'].queryset = ProductVariant.objects.filter(
                variant_filter,
                is_active=True,
            ).select_related('product', 'color', 'size').order_by('product__name', 'color__name', 'size__sort_order', 'size__name')
        else:
            self.fields['product_variant'].queryset = ProductVariant.objects.none()

    def clean(self):
        cleaned = super().clean()
        supplier = cleaned.get('supplier')
        product_variant = cleaned.get('product_variant')
        warehouse = cleaned.get('warehouse')
        quantity = cleaned.get('quantity')

        if supplier and product_variant and product_variant.product.supplier_id != supplier.pk:
            self.add_error('product_variant', 'اختر صنفا خاصا بالمورد المحدد')

        if product_variant and warehouse:
            stock = Stock.objects.filter(variant=product_variant, warehouse=warehouse).first()
            available = stock.quantity if stock else 0
            if available <= 0:
                self.add_error('warehouse', 'هذا الصنف غير موجود في المخزن المحدد')
            elif quantity and quantity > available:
                self.add_error('quantity', f'الكمية المتاحة في المخزن {available}')

        return cleaned
