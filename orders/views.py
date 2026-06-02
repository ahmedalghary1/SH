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
from inventory.models import Stock
from products.models import Product, ProductVariant

from .forms import OrderForm
from .models import Order
from .services import cancel_order, confirm_order, create_order, return_order


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

    def form_valid(self, form):
        raw_items = self.request.POST.get('items_json', '[]')
        try:
            posted_items = json.loads(raw_items)
            items = []
            for posted in posted_items:
                variant = ProductVariant.objects.select_related('product').get(pk=posted['variant_id'], is_active=True)
                items.append({
                    'variant': variant,
                    'quantity': int(posted['quantity']),
                    'unit_price': Decimal(str(posted['unit_price'])),
                    'discount': Decimal(str(posted.get('discount', 0))),
                })
            confirm = self.request.POST.get('action') == 'confirm'
            order = create_order(order_data=form.cleaned_data, items=items, user=self.request.user, confirm=confirm)
            messages.success(self.request, 'تم حفظ الطلب' + (' وتأكيده' if confirm else ' كمسودة'))
            return redirect('orders:detail', pk=order.pk)
        except (ValidationError, ProductVariant.DoesNotExist, KeyError, ValueError, json.JSONDecodeError) as exc:
            form.add_error(None, getattr(exc, 'message', 'بيانات الطلب غير صحيحة'))
            return self.form_invalid(form)


class OrderDetailView(RoleRequiredMixin, DetailView):
    allowed_roles = ('manager', 'sales', 'warehouse')
    model = Order
    template_name = 'orders/detail.html'
    context_object_name = 'order'

    def get_queryset(self):
        qs = Order.objects.select_related('customer', 'warehouse', 'created_by').prefetch_related('items__variant__product', 'items__variant__color', 'items__variant__size')
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
    qs = Product.objects.filter(is_active=True)
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(sku__icontains=q) | Q(variants__variant_sku__icontains=q)).distinct()
    data = [{'id': p.id, 'name': p.name, 'sku': p.sku} for p in qs[:10]]
    return JsonResponse({'success': True, 'message': 'تم جلب المنتجات', 'data': data})


@require_GET
@sales_required
def ajax_get_product_variants(request, product_id):
    variants = ProductVariant.objects.filter(product_id=product_id, is_active=True).select_related('color', 'size')
    data = [{'id': v.id, 'sku': v.variant_sku, 'color': v.color.name if v.color else '', 'size': v.size.name if v.size else ''} for v in variants]
    return JsonResponse({'success': True, 'message': 'تم جلب المتغيرات', 'data': data})


@require_GET
@sales_required
def ajax_get_variant_stock(request, variant_id):
    warehouse_id = request.GET.get('warehouse_id')
    stock = Stock.objects.filter(variant_id=variant_id, warehouse_id=warehouse_id).first()
    return JsonResponse({'success': True, 'message': 'تم جلب المخزون', 'data': {'quantity': stock.quantity if stock else 0}})


@require_GET
@sales_required
def ajax_get_variant_price(request, variant_id):
    order_type = request.GET.get('order_type', 'b2c')
    variant = get_object_or_404(ProductVariant.objects.select_related('product'), pk=variant_id)
    price = variant.product.wholesale_price if order_type == 'b2b' else variant.product.retail_price
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
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'success': False, 'message': 'بيانات غير صحيحة', 'errors': {}}, status=400)
    subtotal = Decimal('0')
    discount = Decimal('0')
    for item in items:
        qty = Decimal(str(item.get('quantity', 0)))
        price = Decimal(str(item.get('unit_price', 0)))
        item_discount = Decimal(str(item.get('discount', 0)))
        subtotal += qty * price
        discount += item_discount
    total = max(subtotal - discount, Decimal('0'))
    remaining = max(total - paid_amount, Decimal('0'))
    return JsonResponse({'success': True, 'message': 'تم الحساب', 'data': {'subtotal': str(subtotal), 'discount': str(discount), 'total': str(total), 'remaining_amount': str(remaining)}})

# Create your views here.
