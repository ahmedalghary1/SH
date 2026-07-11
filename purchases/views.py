from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import CreateView, DetailView, FormView, ListView, TemplateView, UpdateView, View

from accounts.permissions import ManagerRequiredMixin, RoleRequiredMixin, WarehouseRequiredMixin, can_view_costs, role_required
from config.delete_views import ManagerDeleteView
from config.exports import ExportListMixin
from config.search import arabic_search_q
from finance.models import PaymentTransaction
from inventory.models import Stock
from products.models import Category, Color, Product, ProductVariant, Size

from .forms import PurchaseOrderForm, PurchaseReceiveForm, PurchaseReturnForm, SupplierForm, SupplierPaymentForm, SimpleSupplierForm
from .models import PurchaseOrder, Supplier
from .raw_material import RawMaterialPurchaseForm, record_raw_material_purchase
from .services import cancel_purchase_order, create_purchase_order, create_purchase_return, pay_supplier, receive_purchase_order_items, update_purchase_discount


def _decimal_from_post(value, default=Decimal('0')):
    if value in (None, ''):
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise ValidationError('القيمة الرقمية غير صحيحة')


def _int_from_post(value, default=12):
    if value in (None, ''):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValidationError('عدد الدستة غير صحيح')
    if parsed < 1:
        raise ValidationError('عدد الدستة يجب أن يكون أكبر من صفر')
    return parsed


def _get_or_create_named_model(model, selected, new_name, *, defaults=None, missing_message):
    if selected:
        return selected
    name = (new_name or '').strip()
    if not name:
        raise ValidationError(missing_message)
    obj, _ = model.objects.get_or_create(name=name, defaults=defaults or {})
    return obj


def _create_purchase_product_variant(*, name, sku, category, category_name, color, color_name, size, size_name, pieces_per_dozen, retail_price, wholesale_price, unit_cost):
    name = (name or '').strip()
    sku = (sku or '').strip()
    if not name:
        raise ValidationError('اكتب اسم المنتج الجديد')
    if not sku:
        raise ValidationError('اكتب كود المنتج الجديد')
    if Product.objects.filter(sku=sku).exists():
        raise ValidationError('كود المنتج موجود بالفعل')

    category = _get_or_create_named_model(
        Category,
        category,
        category_name,
        defaults={'is_active': True},
        missing_message='اختر التصنيف أو اكتب تصنيف جديد',
    )
    if not category.is_active:
        category.is_active = True
        category.save(update_fields=['is_active'])
    color = _get_or_create_named_model(Color, color, color_name, missing_message='اختر اللون أو اكتب لون جديد')
    size = _get_or_create_named_model(Size, size, size_name, defaults={'sort_order': 0}, missing_message='اختر المقاس أو اكتب مقاس جديد')

    product = Product.objects.create(
        name=name,
        sku=sku,
        category=category,
        retail_price=retail_price,
        wholesale_price=wholesale_price,
        pieces_per_dozen=pieces_per_dozen,
    )
    return ProductVariant.objects.create(
        product=product,
        color=color,
        size=size,
        variant_sku=f'{sku}-{color.pk}-{size.pk}',
        cost_price=unit_cost,
        sale_price=retail_price,
        retail_price=retail_price,
        wholesale_price=wholesale_price,
    )


class SimpleSupplierListView(ManagerRequiredMixin, ListView):
    model = Supplier
    template_name = 'purchases/suppliers/simple_list.html'
    context_object_name = 'suppliers'
    paginate_by = 20

    def get_queryset(self):
        qs = Supplier.objects.filter(is_active=True).annotate(
            total_purchases=Sum('purchase_orders__total_amount', filter=Q(purchase_orders__status__in=[PurchaseOrder.STATUS_RECEIVED, PurchaseOrder.STATUS_PARTIALLY_RECEIVED])),
            total_paid=Sum('purchase_orders__paid_amount', filter=Q(purchase_orders__status__in=[PurchaseOrder.STATUS_RECEIVED, PurchaseOrder.STATUS_PARTIALLY_RECEIVED])),
            last_transaction_date=Max(
                'purchase_orders__created_at',
                filter=~Q(purchase_orders__status=PurchaseOrder.STATUS_CANCELLED)
            ),
        )
        
        q = self.request.GET.get('q')
        debt = self.request.GET.get('debt')
        
        if q:
            qs = qs.filter(arabic_search_q(('name', 'phone', 'company_name'), q))
        if debt == 'yes':
            qs = qs.filter(current_balance__gt=0)
        elif debt == 'no':
            qs = qs.filter(current_balance=0)
        
        return qs.order_by('-created_at')


class SimpleSupplierCreateView(ManagerRequiredMixin, CreateView):
    model = Supplier
    form_class = SimpleSupplierForm
    template_name = 'purchases/suppliers/simple_create.html'
    success_url = reverse_lazy('purchases:simple_supplier_list')

    def form_valid(self, form):
        form.instance.opening_balance = 0
        form.instance.current_balance = 0
        messages.success(self.request, 'تم إضافة المورد')
        return super().form_valid(form)


class SimpleSupplierDetailView(ManagerRequiredMixin, DetailView):
    model = Supplier
    template_name = 'purchases/suppliers/simple_detail.html'
    context_object_name = 'supplier'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        supplier = self.object
        
        # Get purchase orders
        purchase_orders = supplier.purchase_orders.select_related('created_by').order_by('-created_at')
        
        # Get transactions
        transactions = PaymentTransaction.objects.filter(
            related_supplier=supplier,
            direction=PaymentTransaction.DIRECTION_OUT,
            transaction_type=PaymentTransaction.TYPE_SUPPLIER_PAYMENT,
        ).select_related('cash_account', 'created_by').order_by('-created_at')
        
        # Calculate totals
        total_purchases = purchase_orders.aggregate(v=Sum('total_amount'))['v'] or 0
        total_paid = transactions.aggregate(v=Sum('amount'))['v'] or 0
        
        # Get last order and payment
        last_order = purchase_orders.first()
        last_payment = transactions.first()
        
        # Generate statement
        statement = self._generate_statement(supplier, purchase_orders, transactions)
        
        context.update({
            'purchase_orders': purchase_orders[:20],
            'transactions': transactions[:20],
            'summary': {
                'total_purchases': total_purchases,
                'total_paid': total_paid,
                'last_order': last_order,
                'last_payment': last_payment,
            },
            'statement': statement,
        })
        return context

    def _generate_statement(self, supplier, purchase_orders, transactions):
        from decimal import Decimal
        statement = []
        
        # Opening balance
        if supplier.opening_balance and supplier.opening_balance > 0:
            statement.append({
                'date': supplier.created_at,
                'type': 'رصيد افتتاحي',
                'description': 'رصيد افتتاحي',
                'debit': supplier.opening_balance,
                'credit': '',
                'balance': supplier.opening_balance,
            })
        
        # Combine all transactions
        transactions_list = []
        for order in purchase_orders.exclude(status=PurchaseOrder.STATUS_CANCELLED):
            transactions_list.append({
                'date': order.created_at,
                'type': 'فاتورة شراء',
                'description': f'فاتورة {order.purchase_number}',
                'debit': order.total_amount,
                'credit': '',
                'order': order,
            })
        
        for payment in transactions:
            transactions_list.append({
                'date': payment.created_at,
                'type': 'دفع للمورد',
                'description': payment.notes or 'دفع',
                'debit': '',
                'credit': payment.amount,
                'payment': payment,
            })
        
        # Sort by date
        transactions_list.sort(key=lambda x: x['date'])
        
        # Calculate running balance
        balance = supplier.opening_balance or Decimal('0')
        for trans in transactions_list:
            if trans['debit']:
                balance += trans['debit']
            if trans['credit']:
                balance -= trans['credit']
            trans['balance'] = balance
            statement.append(trans)
        
        return statement


class SupplierListView(ManagerRequiredMixin, ExportListMixin, ListView):
    model = Supplier
    template_name = 'purchases/suppliers/list.html'
    context_object_name = 'suppliers'
    paginate_by = 20
    export_title = 'قائمة الموردين'
    export_filename = 'suppliers'
    export_columns = (
        ('اسم المورد', 'name'),
        ('الشركة', 'company_name'),
        ('الهاتف', 'phone'),
        ('البريد', 'email'),
        ('الرصيد الافتتاحي', 'opening_balance'),
        ('الرصيد الحالي', 'current_balance'),
        ('الحالة', lambda supplier: 'نشط' if supplier.is_active else 'متوقف'),
    )

    def get_queryset(self):
        qs = Supplier.objects.order_by('-created_at')
        q = self.request.GET.get('q')
        if q:
            qs = qs.filter(arabic_search_q(('name', 'phone', 'company_name'), q))
        return qs


class SupplierCreateView(ManagerRequiredMixin, CreateView):
    model = Supplier
    form_class = SupplierForm
    template_name = 'purchases/suppliers/form.html'
    success_url = reverse_lazy('purchases:suppliers')

    def form_valid(self, form):
        form.instance.opening_balance = 0
        form.instance.current_balance = 0
        messages.success(self.request, 'تم إنشاء المورد')
        return super().form_valid(form)


class SupplierUpdateView(ManagerRequiredMixin, UpdateView):
    model = Supplier
    form_class = SupplierForm
    template_name = 'purchases/suppliers/form.html'
    success_url = reverse_lazy('purchases:suppliers')

    def form_valid(self, form):
        messages.success(self.request, 'تم تحديث المورد')
        return super().form_valid(form)


class SupplierDeleteView(ManagerDeleteView):
    model = Supplier
    success_url = reverse_lazy('purchases:suppliers')
    success_message = 'تم حذف المورد'


class RawMaterialPurchaseView(ManagerRequiredMixin, FormView):
    template_name = 'purchases/suppliers/raw_purchase.html'
    form_class = RawMaterialPurchaseForm
    success_url = reverse_lazy('purchases:suppliers')

    def get_initial(self):
        initial = super().get_initial()
        supplier_id = self.request.GET.get('supplier')
        if supplier_id:
            initial['supplier'] = supplier_id
            initial['operation_type'] = 'raw_material'
        return initial

    def form_valid(self, form):
        try:
            record_raw_material_purchase(
                raw_name=form.cleaned_data['raw_name'],
                supplier=form.cleaned_data['supplier'],
                amount=form.cleaned_data['amount'],
                notes=form.cleaned_data.get('notes') or '',
                user=self.request.user,
            )
            messages.success(self.request, 'تم تسجيل شراء الخام وخصم السعر من الخزنة')
            return redirect(self.success_url)
        except ValidationError as exc:
            form.add_error(None, exc.message)
            return self.form_invalid(form)


class SupplierDetailView(ManagerRequiredMixin, DetailView):
    model = Supplier
    template_name = 'purchases/suppliers/detail.html'
    context_object_name = 'supplier'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['purchase_orders'] = self.object.purchase_orders.order_by('-created_at')[:20]
        context['transactions'] = self.object.payment_transactions.select_related('cash_account', 'created_by')[:20]
        return context


class SupplierStatementView(ManagerRequiredMixin, DetailView):
    model = Supplier
    template_name = 'purchases/suppliers/statement.html'
    context_object_name = 'supplier'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['purchase_orders'] = self.object.purchase_orders.order_by('-created_at')
        context['transactions'] = self.object.payment_transactions.select_related('cash_account', 'created_by')
        return context


class PurchaseOrderListView(ManagerRequiredMixin, ExportListMixin, ListView):
    model = PurchaseOrder
    template_name = 'purchases/orders/list.html'
    context_object_name = 'purchase_orders'
    paginate_by = 20
    export_title = 'قائمة شراء البضاعة'
    export_filename = 'direct-purchases'
    export_columns = (
        ('رقم الشراء', 'purchase_number'),
        ('المورد', 'supplier'),
        ('الحالة', 'get_status_display'),
        ('تاريخ الطلب', 'order_date'),
        ('التاريخ المتوقع', 'expected_date'),
        ('الإجمالي', 'total_amount'),
        ('المدفوع', 'paid_amount'),
        ('المتبقي', 'remaining_amount'),
        ('الموظف', 'created_by'),
    )

    def get_queryset(self):
        qs = PurchaseOrder.objects.select_related('supplier', 'created_by').order_by('-created_at')
        status = self.request.GET.get('status')
        if status:
            qs = qs.filter(status=status)
        return qs


class PurchaseOrderCreateView(ManagerRequiredMixin, FormView):
    template_name = 'purchases/orders/create.html'
    form_class = PurchaseOrderForm

    def get_or_create_supplier(self, form):
        supplier = form.cleaned_data.get('supplier')
        if supplier:
            return supplier
        supplier = Supplier.objects.create(
            name=(form.cleaned_data.get('new_supplier_name') or '').strip(),
            phone=(form.cleaned_data.get('new_supplier_phone') or '').strip() or None,
            is_active=True,
        )
        return supplier

    def get_or_create_product_variant(self, form):
        variant = form.cleaned_data.get('product_variant')
        if variant:
            return variant

        return _create_purchase_product_variant(
            name=form.cleaned_data.get('new_product_name'),
            sku=form.cleaned_data.get('new_product_sku'),
            category=form.cleaned_data.get('new_category'),
            category_name=form.cleaned_data.get('new_category_name'),
            color=form.cleaned_data.get('new_color'),
            color_name=form.cleaned_data.get('new_color_name'),
            size=form.cleaned_data.get('new_size'),
            size_name=form.cleaned_data.get('new_size_name'),
            pieces_per_dozen=form.cleaned_data.get('pieces_per_dozen') or 12,
            retail_price=form.cleaned_data.get('retail_price') or 0,
            wholesale_price=form.cleaned_data.get('wholesale_price') or 0,
            unit_cost=form.cleaned_data.get('unit_cost') or 0,
        )

    def build_purchase_items(self, form):
        posted_items = form.cleaned_data.get('purchase_items') or []
        if posted_items:
            items = []
            for posted in posted_items:
                try:
                    product_variant = ProductVariant.objects.get(pk=posted['variant_id'], is_active=True)
                except ProductVariant.DoesNotExist:
                    raise ValidationError('الصنف المحدد غير صحيح')
                items.append({
                    'product_variant': product_variant,
                    'quantity': posted['quantity'],
                    'unit_cost': posted['unit_cost'],
                })
            return items

        product_variant = self.get_or_create_product_variant(form)
        return [{
            'product_variant': product_variant,
            'quantity': form.cleaned_data['quantity'],
            'unit_cost': form.cleaned_data['unit_cost'],
        }]

    def form_valid(self, form):
        try:
            with transaction.atomic():
                supplier = self.get_or_create_supplier(form)
                items = self.build_purchase_items(form)
                po = create_purchase_order(
                    supplier=supplier,
                    status=PurchaseOrder.STATUS_ORDERED,
                    order_date=form.cleaned_data.get('order_date'),
                    expected_date=form.cleaned_data.get('expected_date'),
                    notes=form.cleaned_data.get('notes') or '',
                    items=items,
                    user=self.request.user,
                    discount_type=form.cleaned_data['discount_type'],
                    discount_value=form.cleaned_data.get('discount_value') or Decimal('0'),
                )
                receive_purchase_order_items(
                    purchase_order=po,
                    warehouse=form.cleaned_data['warehouse'],
                    received_items={item.pk: item.quantity for item in po.items.all()},
                    user=self.request.user,
                    note=form.cleaned_data.get('notes') or '',
                )
                paid_amount = form.cleaned_data.get('paid_amount') or Decimal('0')
                if paid_amount > 0:
                    pay_supplier(
                        purchase_order=po,
                        cash_account=form.cleaned_data['cash_account'],
                        amount=paid_amount,
                        user=self.request.user,
                        notes=form.cleaned_data.get('notes') or f'شراء مباشر {po.purchase_number}',
                    )
            if po.remaining_amount > 0:
                messages.success(self.request, 'تم تسجيل شراء البضاعة وإضافتها للمخزن وتسجيل المتبقي على المورد')
            else:
                messages.success(self.request, 'تم تسجيل شراء البضاعة وإضافتها للمخزن')
            return redirect('purchases:order_detail', pk=po.pk)
        except ValidationError as exc:
            form.add_error(None, exc.message)
            return self.form_invalid(form)


@require_POST
@role_required('manager')
def ajax_quick_create_purchase_supplier(request):
    name = request.POST.get('new_supplier_name', '').strip() or request.POST.get('name', '').strip()
    phone = request.POST.get('new_supplier_phone', '').strip() or request.POST.get('phone', '').strip()
    if not name:
        return JsonResponse({'success': False, 'message': 'اكتب اسم المورد'}, status=400)

    supplier = Supplier.objects.create(name=name, phone=phone or None, is_active=True)
    return JsonResponse({
        'success': True,
        'message': 'تم إضافة المورد',
        'data': {'id': supplier.id, 'name': supplier.name, 'phone': supplier.phone or ''},
    })


@require_POST
@role_required('manager')
def ajax_quick_create_purchase_product(request):
    def selected(model, key):
        value = request.POST.get(key)
        if not value:
            return None
        obj = model.objects.filter(pk=value).first()
        if not obj:
            raise ValidationError('الاختيار المحدد غير صحيح')
        return obj

    try:
        with transaction.atomic():
            variant = _create_purchase_product_variant(
                name=request.POST.get('new_product_name'),
                sku=request.POST.get('new_product_sku'),
                category=selected(Category, 'new_category'),
                category_name=request.POST.get('new_category_name'),
                color=selected(Color, 'new_color'),
                color_name=request.POST.get('new_color_name'),
                size=selected(Size, 'new_size'),
                size_name=request.POST.get('new_size_name'),
                pieces_per_dozen=_int_from_post(request.POST.get('pieces_per_dozen'), 12),
                retail_price=_decimal_from_post(request.POST.get('retail_price')),
                wholesale_price=_decimal_from_post(request.POST.get('wholesale_price')),
                unit_cost=_decimal_from_post(request.POST.get('unit_cost')),
            )
    except ValidationError as exc:
        message = getattr(exc, 'message', None) or '; '.join(exc.messages)
        return JsonResponse({'success': False, 'message': message}, status=400)

    return JsonResponse({
        'success': True,
        'message': 'تم إضافة المنتج',
        'data': {
            'id': variant.id,
            'name': str(variant),
            'sku': variant.variant_sku,
            'pieces_per_dozen': variant.product.pieces_per_dozen,
        },
    })


@require_GET
@role_required('manager')
def ajax_supplier_product_variants(request):
    stocks = Stock.objects.filter(
        quantity__gt=0,
        warehouse__is_active=True,
        variant__is_active=True,
    ).select_related('variant__product', 'variant__color', 'variant__size')
    totals = {}
    variants = {}
    for stock in stocks:
        variants[stock.variant_id] = stock.variant
        totals[stock.variant_id] = totals.get(stock.variant_id, 0) + stock.quantity

    data = [
        {
            'id': variant.pk,
            'name': str(variant),
            'available_quantity': totals[variant.pk],
        }
        for variant in sorted(variants.values(), key=lambda item: (item.product.name, item.color.name if item.color else '', item.size.sort_order if item.size else 0, item.size.name if item.size else ''))
    ]
    return JsonResponse({'success': True, 'message': 'تم جلب الأصناف', 'data': {'variants': data}})


class PurchaseOrderDetailView(RoleRequiredMixin, DetailView):
    allowed_roles = ('manager', 'warehouse')
    model = PurchaseOrder
    template_name = 'purchases/orders/detail.html'
    context_object_name = 'purchase_order'

    def get_queryset(self):
        return PurchaseOrder.objects.select_related('supplier', 'created_by').prefetch_related('items__product_variant__product')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['can_view_costs'] = can_view_costs(self.request.user)
        return context


@require_POST
@role_required('manager')
def update_purchase_order_discount(request, pk):
    purchase_order = get_object_or_404(PurchaseOrder, pk=pk)
    try:
        update_purchase_discount(
            purchase_order=purchase_order,
            discount_type=request.POST.get('discount_type') or PurchaseOrder.DISCOUNT_FIXED,
            discount_value=Decimal(request.POST.get('discount_value') or '0'),
            user=request.user,
        )
        messages.success(request, 'تم تحديث خصم فاتورة الشراء وإعادة حساب رصيد المورد')
    except (ValidationError, InvalidOperation) as exc:
        messages.error(request, getattr(exc, 'message', None) or 'قيمة الخصم غير صحيحة')
    return redirect('purchases:order_detail', pk=pk)


class PurchaseReceiveView(WarehouseRequiredMixin, FormView):
    template_name = 'purchases/orders/receive.html'
    form_class = PurchaseReceiveForm

    def dispatch(self, request, *args, **kwargs):
        self.purchase_order = get_object_or_404(PurchaseOrder, pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['purchase_order'] = self.purchase_order
        return kwargs

    def form_valid(self, form):
        try:
            receive_purchase_order_items(
                purchase_order=self.purchase_order,
                warehouse=form.cleaned_data['warehouse'],
                received_items=form.received_items(),
                user=self.request.user,
                note=form.cleaned_data.get('note') or '',
            )
            messages.success(self.request, 'تم تسجيل استلام البضاعة')
            return redirect('purchases:order_detail', pk=self.purchase_order.pk)
        except ValidationError as exc:
            form.add_error(None, exc.message)
            return self.form_invalid(form)


class SupplierPaymentView(ManagerRequiredMixin, FormView):
    template_name = 'purchases/orders/pay.html'
    form_class = SupplierPaymentForm

    def dispatch(self, request, *args, **kwargs):
        self.purchase_order = get_object_or_404(PurchaseOrder, pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        try:
            pay_supplier(
                purchase_order=self.purchase_order,
                cash_account=form.cleaned_data['cash_account'],
                amount=form.cleaned_data['amount'],
                user=self.request.user,
                notes=form.cleaned_data.get('notes') or '',
            )
            messages.success(self.request, 'تم تسجيل دفع المورد')
            return redirect('purchases:order_detail', pk=self.purchase_order.pk)
        except ValidationError as exc:
            form.add_error(None, exc.message)
            return self.form_invalid(form)


class PurchaseReturnView(ManagerRequiredMixin, FormView):
    template_name = 'purchases/orders/return.html'
    form_class = PurchaseReturnForm
    success_url = reverse_lazy('purchases:orders')

    def form_valid(self, form):
        try:
            create_purchase_return(user=self.request.user, **form.cleaned_data)
            messages.success(self.request, 'تم تسجيل مرتجع الشراء وخصمه من المخزن وحساب المورد')
            return redirect(self.success_url)
        except ValidationError as exc:
            form.add_error(None, getattr(exc, 'message', str(exc)))
            return self.form_invalid(form)


class PurchaseOrderCancelView(ManagerRequiredMixin, View):
    def post(self, request, pk):
        purchase_order = get_object_or_404(PurchaseOrder, pk=pk)
        try:
            cancel_purchase_order(purchase_order=purchase_order, user=request.user)
            messages.success(request, 'تم إلغاء أمر الشراء')
        except ValidationError as exc:
            messages.error(request, exc.message)
        return redirect('purchases:order_detail', pk=pk)


class PurchaseOrderDeleteView(ManagerDeleteView):
    model = PurchaseOrder
    success_url = reverse_lazy('purchases:orders')
    success_message = 'تم حذف أمر الشراء'


class PurchaseReportView(ManagerRequiredMixin, TemplateView):
    template_name = 'purchases/reports/purchases.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        orders = PurchaseOrder.objects.exclude(status=PurchaseOrder.STATUS_CANCELLED)
        agg = orders.aggregate(
            total_amount=Sum('total_amount'),
            paid_amount=Sum('paid_amount'),
            remaining_amount=Sum('remaining_amount'),
        )
        context['orders'] = orders.select_related('supplier').order_by('-created_at')[:100]
        context['total_amount'] = agg['total_amount'] or 0
        context['paid_amount'] = agg['paid_amount'] or 0
        context['remaining_amount'] = agg['remaining_amount'] or 0
        return context


class SupplierDueReportView(ManagerRequiredMixin, TemplateView):
    template_name = 'purchases/reports/supplier_dues.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['suppliers'] = Supplier.objects.filter(is_active=True, current_balance__gt=0).order_by('-current_balance')
        context['total_due'] = context['suppliers'].aggregate(v=Sum('current_balance'))['v'] or 0
        context['payments'] = PaymentTransaction.objects.filter(
            transaction_type=PaymentTransaction.TYPE_SUPPLIER_PAYMENT,
        ).select_related('related_supplier', 'cash_account')[:50]
        return context
