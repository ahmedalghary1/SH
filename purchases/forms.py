import json
from decimal import Decimal, InvalidOperation

from django import forms

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
    items_json = forms.CharField(required=False, widget=forms.HiddenInput)
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
    cash_account = forms.ModelChoiceField(queryset=CashAccount.objects.filter(is_active=True), label='الخزنة', required=False)
    paid_amount = forms.DecimalField(min_value=0, required=False, initial=0, label='المدفوع الآن')
    quantity = forms.IntegerField(min_value=1, label='الكمية', required=False)
    unit_cost = forms.DecimalField(min_value=0, label='سعر الشراء', required=False)
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
        items = self._clean_items_json(cleaned.get('items_json'))
        if items:
            cleaned['purchase_items'] = items
            self._clean_payment(cleaned, items)
            return cleaned
        if cleaned.get('product_variant'):
            if not cleaned.get('quantity'):
                self.add_error('quantity', 'أدخل الكمية')
            if cleaned.get('unit_cost') is None:
                self.add_error('unit_cost', 'أدخل سعر الشراء')
            cleaned['purchase_items'] = [{
                'variant_id': str(cleaned['product_variant'].pk),
                'quantity': cleaned.get('quantity'),
                'unit_cost': cleaned.get('unit_cost'),
            }]
            self._clean_payment(cleaned, cleaned['purchase_items'])
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
        if not cleaned.get('quantity'):
            self.add_error('quantity', 'أدخل الكمية')
        if cleaned.get('unit_cost') is None:
            self.add_error('unit_cost', 'أدخل سعر الشراء')
        if cleaned.get('quantity') and cleaned.get('unit_cost') is not None:
            self._clean_payment(cleaned, [{
                'quantity': cleaned.get('quantity'),
                'unit_cost': cleaned.get('unit_cost'),
            }])
        return cleaned

    def _clean_payment(self, cleaned, items):
        paid_amount = cleaned.get('paid_amount') or Decimal('0')
        cleaned['paid_amount'] = paid_amount
        total = sum(
            Decimal(str(item.get('quantity') or 0)) * Decimal(str(item.get('unit_cost') or 0))
            for item in items
        )
        if paid_amount > total:
            self.add_error('paid_amount', 'المدفوع لا يمكن أن يتجاوز إجمالي الفاتورة')
        if paid_amount > 0 and not cleaned.get('cash_account'):
            self.add_error('cash_account', 'اختر الخزنة عند تسجيل مبلغ مدفوع')

    def _clean_items_json(self, raw_items):
        if not raw_items:
            return []
        try:
            posted_items = json.loads(raw_items)
        except json.JSONDecodeError:
            raise forms.ValidationError('بيانات الأصناف غير صحيحة')
        if not isinstance(posted_items, list):
            raise forms.ValidationError('بيانات الأصناف غير صحيحة')

        items = []
        for posted in posted_items:
            if not isinstance(posted, dict):
                raise forms.ValidationError('بيانات الأصناف غير صحيحة')
            variant_id = str(posted.get('product_variant_id') or posted.get('variant_id') or '').strip()
            if not variant_id:
                raise forms.ValidationError('اختر الصنف لكل بند')
            try:
                quantity_decimal = Decimal(str(posted.get('quantity')))
            except (InvalidOperation, TypeError):
                raise forms.ValidationError('كمية الشراء غير صحيحة')
            if not quantity_decimal.is_finite() or quantity_decimal != quantity_decimal.to_integral_value():
                raise forms.ValidationError('كمية الشراء غير صحيحة')
            quantity = int(quantity_decimal)
            if quantity <= 0:
                raise forms.ValidationError('كمية الشراء يجب أن تكون أكبر من صفر')
            try:
                unit_cost = Decimal(str(posted.get('unit_cost')))
            except (InvalidOperation, TypeError):
                raise forms.ValidationError('سعر الشراء غير صحيح')
            if not unit_cost.is_finite():
                raise forms.ValidationError('سعر الشراء غير صحيح')
            if unit_cost < 0:
                raise forms.ValidationError('سعر الشراء لا يمكن أن يكون سالبا')
            items.append({
                'variant_id': variant_id,
                'quantity': quantity,
                'unit_cost': unit_cost,
            })
        return items


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
        self.fields['supplier'].widget.attrs.update({'data-purchase-return-supplier': 'true'})
        self.fields['product_variant'].widget.attrs.update({'data-purchase-return-variant': 'true'})
        self.fields['warehouse'].widget.attrs.update({'data-purchase-return-warehouse': 'true'})
        self.fields['product_variant'].queryset = ProductVariant.objects.filter(
            is_active=True,
        ).select_related('product', 'color', 'size').order_by('product__name', 'color__name', 'size__sort_order', 'size__name')

    def clean(self):
        cleaned = super().clean()
        product_variant = cleaned.get('product_variant')
        warehouse = cleaned.get('warehouse')
        quantity = cleaned.get('quantity')

        if product_variant and warehouse:
            stock = Stock.objects.filter(variant=product_variant, warehouse=warehouse).first()
            available = stock.quantity if stock else 0
            if available <= 0:
                self.add_error('warehouse', 'هذا الصنف غير موجود في المخزن المحدد')
            elif quantity and quantity > available:
                self.add_error('quantity', f'الكمية المتاحة في المخزن {available}')

        return cleaned
