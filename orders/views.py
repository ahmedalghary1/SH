import json
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import DetailView, FormView, ListView, UpdateView, View

from accounts.permissions import RoleRequiredMixin, SalesRequiredMixin, sales_required
from customers.models import Customer
from invoices.services import generate_invoice
from inventory.models import Stock, Warehouse
from products.models import Product, ProductVariant

from .forms import OrderForm
from .models import Order
from .services import (
    calculate_discount_amount,
    cancel_order,
    confirm_order,
    create_order,
    get_price_for_customer,
    prepare_order_item_pricing,
    return_order,
)


def _is_restricted_sales_user(user):
    return user.role == 'sales' and not user.is_superuser


def _available_variants_for_user(user):
    qs = ProductVariant.objects.filter(is_active=True)
    if _is_restricted_sales_user(user):
        qs = qs.filter(
            stock__quantity__gt=0,
            stock__warehouse__is_active=True,
            stock__warehouse__assigned_user=user,
            stock__warehouse__warehouse_type=Warehouse.TYPE_REPRESENTATIVE,
        ).distinct()
    return qs


def _available_products_for_user(user):
    qs = Product.objects.filter(is_active=True)
    if _is_restricted_sales_user(user):
        qs = qs.filter(
            variants__is_active=True,
            variants__stock__quantity__gt=0,
            variants__stock__warehouse__is_active=True,
            variants__stock__warehouse__assigned_user=user,
            variants__stock__warehouse__warehouse_type=Warehouse.TYPE_REPRESENTATIVE,
        ).distinct()
    return qs


class OrderListView(RoleRequiredMixin, ListView):
    allowed_roles = ('manager', 'sales', 'warehouse')
    model = Order
    template_name = 'orders/list.html'
    context_object_name = 'orders'
    paginate_by = 20

    def get_queryset(self):
        qs = Order.objects.select_related('customer', 'warehouse', 'created_by').order_by('-created_at')
        if self.request.user.role == 'sales' and not self.request.user.is_superuser:
            qs = qs.filter(created_by=self.request.user)
        q = self.request.GET.get('q')
        status = self.request.GET.get('status')
        if q:
            qs = qs.filter(Q(order_number__icontains=q) | Q(customer__name__icontains=q) | Q(customer__phone__icontains=q))
        if status:
            qs = qs.filter(status=status)
        return qs


class OrderCreateView(SalesRequiredMixin, FormView):
    form_class = OrderForm
    template_name = 'orders/create.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_item_warehouse(self, warehouse_id):
        warehouses = Warehouse.objects.filter(is_active=True)
        if self.request.user.role == 'sales' and not self.request.user.is_superuser:
            warehouses = warehouses.filter(assigned_user=self.request.user, warehouse_type=Warehouse.TYPE_REPRESENTATIVE)
        return warehouses.get(pk=warehouse_id)

    def form_valid(self, form):
        raw_items = self.request.POST.get('items_json', '[]')
        try:
            posted_items = json.loads(raw_items)
            items = []
            for posted in posted_items:
                variant = _available_variants_for_user(self.request.user).select_related('product').get(pk=posted['variant_id'])
                warehouse = self.get_item_warehouse(posted['warehouse_id'])
                quantity = int(posted['quantity'])
                if _is_restricted_sales_user(self.request.user):
                    available_stock = Stock.objects.filter(
                        warehouse=warehouse,
                        variant=variant,
                        quantity__gte=quantity,
                    ).exists()
                    if not available_stock:
                        raise ValidationError('الكمية غير متاحة في عهدة المندوب')
                items.append({
                    'variant': variant,
                    'warehouse': warehouse,
                    'quantity': quantity,
                    'unit_price': Decimal(str(posted.get('unit_price', 0))),
                    'discount_amount': Decimal(str(posted.get('discount_amount', posted.get('discount', 0)))),
                    'discount_percentage': Decimal(str(posted.get('discount_percentage', 0))),
                })
            confirm = self.request.POST.get('action') == 'confirm'
            order = create_order(order_data=form.cleaned_data, items=items, user=self.request.user, confirm=confirm)
            if confirm:
                invoice = generate_invoice(order, user=self.request.user)
                messages.success(self.request, 'تم حفظ الفاتورة وخصم الكمية من المخزون')
                return redirect('invoices:detail', pk=invoice.pk)
            messages.success(self.request, 'تم حفظ الطلب' + (' وتأكيده' if confirm else ' كمسودة'))
            return redirect('orders:detail', pk=order.pk)
        except (ValidationError, ProductVariant.DoesNotExist, Warehouse.DoesNotExist, KeyError, ValueError, json.JSONDecodeError) as exc:
            form.add_error(None, getattr(exc, 'message', 'بيانات الطلب غير صحيحة'))
            return self.form_invalid(form)


class OrderDetailView(RoleRequiredMixin, DetailView):
    allowed_roles = ('manager', 'sales', 'warehouse')
    model = Order
    template_name = 'orders/detail.html'
    context_object_name = 'order'

    def get_queryset(self):
        qs = Order.objects.select_related('customer', 'warehouse', 'created_by', 'discount_approved_by').prefetch_related(
            'items__warehouse', 'items__variant__product', 'items__variant__color', 'items__variant__size',
        )
        if self.request.user.role == 'sales' and not self.request.user.is_superuser:
            qs = qs.filter(created_by=self.request.user)
        return qs


class OrderUpdateView(RoleRequiredMixin, UpdateView):
    allowed_roles = ('manager',)
    model = Order
    form_class = OrderForm
    template_name = 'orders/update.html'

    def get_success_url(self):
        return reverse_lazy('orders:detail', kwargs={'pk': self.object.pk})


class OrderConfirmView(SalesRequiredMixin, View):
    def post(self, request, pk):
        order = get_object_or_404(Order, pk=pk)
        try:
            confirm_order(order=order, user=request.user)
            messages.success(request, 'تم تأكيد الطلب وخصم المخزون')
        except ValidationError as exc:
            messages.error(request, exc.message)
        return redirect('orders:detail', pk=pk)


class OrderCancelView(SalesRequiredMixin, View):
    def post(self, request, pk):
        order = get_object_or_404(Order, pk=pk)
        try:
            cancel_order(order=order, user=request.user)
            messages.success(request, 'تم إلغاء الطلب')
        except ValidationError as exc:
            messages.error(request, exc.message)
        return redirect('orders:detail', pk=pk)


class OrderReturnView(SalesRequiredMixin, View):
    def post(self, request, pk):
        order = get_object_or_404(Order, pk=pk)
        try:
            return_order(order=order, user=request.user)
            messages.success(request, 'تم تسجيل المرتجع')
        except ValidationError as exc:
            messages.error(request, exc.message)
        return redirect('orders:detail', pk=pk)


class OrderStatusUpdateView(RoleRequiredMixin, View):
    allowed_roles = ('manager', 'warehouse')

    def post(self, request, pk):
        order = get_object_or_404(Order, pk=pk)
        status = request.POST.get('status')
        allowed = {Order.STATUS_PREPARING, Order.STATUS_READY, Order.STATUS_COMPLETED}
        if status in allowed:
            order.status = status
            order.save(update_fields=['status'])
            messages.success(request, 'تم تحديث حالة الطلب')
        else:
            messages.error(request, 'حالة غير مسموحة')
        return redirect('orders:detail', pk=pk)


@require_GET
@sales_required
def ajax_search_products(request):
    q = request.GET.get('q', '').strip()
    qs = _available_products_for_user(request.user)
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(sku__icontains=q) | Q(variants__variant_sku__icontains=q)).distinct()
    data = [{'id': p.id, 'name': p.name, 'sku': p.sku} for p in qs[:10]]
    return JsonResponse({'success': True, 'message': 'تم جلب المنتجات', 'data': data})


@require_GET
@sales_required
def ajax_get_product_variants(request, product_id):
    variants = _available_variants_for_user(request.user).filter(product_id=product_id).select_related('color', 'size')
    data = [{'id': v.id, 'sku': v.variant_sku, 'color': v.color.name if v.color else '', 'size': v.size.name if v.size else ''} for v in variants]
    return JsonResponse({'success': True, 'message': 'تم جلب المتغيرات', 'data': data})


@require_GET
@sales_required
def ajax_get_variant_stock(request, variant_id):
    warehouse_id = request.GET.get('warehouse_id')
    stocks = Stock.objects.filter(
        variant_id=variant_id,
        quantity__gt=0,
        warehouse__is_active=True,
    ).select_related('warehouse')
    if request.user.role == 'sales' and not request.user.is_superuser:
        stocks = stocks.filter(warehouse__assigned_user=request.user, warehouse__warehouse_type=Warehouse.TYPE_REPRESENTATIVE)
    if warehouse_id:
        stock = stocks.filter(warehouse_id=warehouse_id).first()
        return JsonResponse({'success': True, 'message': 'تم جلب المخزون', 'data': {'quantity': stock.quantity if stock else 0}})
    data = [
        {
            'warehouse_id': stock.warehouse_id,
            'warehouse_name': stock.warehouse.name,
            'quantity': stock.quantity,
        }
        for stock in stocks.order_by('warehouse__name')
    ]
    return JsonResponse({'success': True, 'message': 'تم جلب المخزون', 'data': {'warehouses': data}})


@require_GET
@sales_required
def ajax_get_variant_price(request, variant_id):
    order_type = request.GET.get('order_type', Order.TYPE_B2C)
    customer_id = request.GET.get('customer_id')
    variant = get_object_or_404(_available_variants_for_user(request.user).select_related('product'), pk=variant_id)
    customer = Customer.objects.filter(pk=customer_id).first() if customer_id else None
    price = get_price_for_customer(variant, customer=customer, order_type=order_type)
    return JsonResponse({'success': True, 'message': 'تم جلب السعر', 'data': {'price': str(price)}})


@require_GET
@sales_required
def ajax_search_customers(request):
    q = request.GET.get('q', '').strip()
    qs = Customer.objects.filter(is_active=True)
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(phone__icontains=q) | Q(company_name__icontains=q))
    data = [{'id': c.id, 'name': c.name, 'phone': c.phone, 'customer_type': c.customer_type} for c in qs[:10]]
    return JsonResponse({'success': True, 'message': 'تم جلب العملاء', 'data': data})


@require_POST
@sales_required
def ajax_calculate_order_totals(request):
    try:
        payload = json.loads(request.body.decode('utf-8'))
        items = payload.get('items', [])
        paid_amount = Decimal(str(payload.get('paid_amount', 0)))
        order_discount_amount = Decimal(str(payload.get('discount_amount', payload.get('discount', 0))))
        order_discount_percentage = Decimal(str(payload.get('discount_percentage', 0)))
        customer = Customer.objects.filter(pk=payload.get('customer_id')).first()
        order_type = payload.get('order_type', Order.TYPE_B2C)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'success': False, 'message': 'بيانات غير صحيحة', 'errors': {}}, status=400)

    subtotal = Decimal('0')
    discount = Decimal('0')
    try:
        for item in items:
            variant = _available_variants_for_user(request.user).select_related('product').get(pk=item.get('variant_id'))
            quantity = Decimal(str(item.get('quantity', 0)))
            pricing = prepare_order_item_pricing(
                variant=variant,
                quantity=item.get('quantity', 0),
                user=request.user,
                customer=customer,
                order_type=order_type,
                unit_price=item.get('unit_price'),
                discount_amount=item.get('discount_amount', item.get('discount', 0)),
                discount_percentage=item.get('discount_percentage', 0),
            )
            subtotal += pricing['original_unit_price'] * quantity
            discount += pricing['line_discount']
        order_discount = calculate_discount_amount(
            base_amount=max(subtotal - discount, Decimal('0')),
            discount_amount=order_discount_amount,
            discount_percentage=order_discount_percentage,
        )
    except (ProductVariant.DoesNotExist, ValidationError, ValueError) as exc:
        return JsonResponse({'success': False, 'message': getattr(exc, 'message', 'بيانات الخصم غير صحيحة'), 'errors': {}}, status=400)

    total_discount = discount + order_discount
    total = max(subtotal - total_discount, Decimal('0'))
    remaining = max(total - paid_amount, Decimal('0'))
    return JsonResponse({
        'success': True,
        'message': 'تم الحساب',
        'data': {
            'subtotal': str(subtotal),
            'discount': str(total_discount),
            'total': str(total),
            'remaining_amount': str(remaining),
        },
    })
