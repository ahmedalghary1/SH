from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import F, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.decorators.http import require_GET
from django.views.generic import CreateView, FormView, ListView

from accounts.permissions import ManagerRequiredMixin, RoleRequiredMixin, WarehouseRequiredMixin
from products.models import ProductVariant

from .forms import StockAdjustmentForm, StockMovementForm, StockTransferForm, WarehouseForm
from .models import Stock, StockMovement, Warehouse
from .services import adjust_stock, stock_in, stock_out, transfer_stock


class WarehouseListView(RoleRequiredMixin, ListView):
    allowed_roles = ('manager', 'warehouse')
    model = Warehouse
    template_name = 'inventory/warehouses/list.html'
    context_object_name = 'warehouses'
    paginate_by = 20


class WarehouseCreateView(ManagerRequiredMixin, CreateView):
    model = Warehouse
    form_class = WarehouseForm
    template_name = 'inventory/warehouses/create.html'
    success_url = reverse_lazy('inventory:warehouses')


class StockListView(RoleRequiredMixin, ListView):
    allowed_roles = ('manager', 'sales', 'warehouse')
    model = Stock
    template_name = 'inventory/stock/list.html'
    context_object_name = 'stocks'
    paginate_by = 30

    def get_queryset(self):
        qs = Stock.objects.select_related('warehouse', 'variant__product', 'variant__color', 'variant__size')
        q = self.request.GET.get('q')
        if q:
            qs = qs.filter(Q(variant__product__name__icontains=q) | Q(variant__variant_sku__icontains=q))
        low = self.request.GET.get('low')
        if low:
            qs = qs.filter(quantity__lte=F('min_quantity'))
        return qs.order_by('warehouse__name', 'variant__product__name')


class StockMovementListView(RoleRequiredMixin, ListView):
    allowed_roles = ('manager', 'warehouse')
    model = StockMovement
    template_name = 'inventory/movements/list.html'
    context_object_name = 'movements'
    paginate_by = 30

    def get_queryset(self):
        return StockMovement.objects.select_related('variant__product', 'from_warehouse', 'to_warehouse', 'created_by').order_by('-created_at')


class StockInView(WarehouseRequiredMixin, FormView):
    template_name = 'inventory/movements/stock_in.html'
    form_class = StockMovementForm
    success_url = reverse_lazy('inventory:movements')

    def form_valid(self, form):
        try:
            stock_in(user=self.request.user, **form.cleaned_data)
            messages.success(self.request, 'تم تسجيل دخول المخزون')
            return redirect(self.success_url)
        except ValidationError as exc:
            form.add_error(None, exc.message)
            return self.form_invalid(form)


class StockOutView(WarehouseRequiredMixin, FormView):
    template_name = 'inventory/movements/stock_out.html'
    form_class = StockMovementForm
    success_url = reverse_lazy('inventory:movements')

    def form_valid(self, form):
        try:
            stock_out(user=self.request.user, **form.cleaned_data)
            messages.success(self.request, 'تم تسجيل خروج المخزون')
            return redirect(self.success_url)
        except ValidationError as exc:
            form.add_error(None, exc.message)
            return self.form_invalid(form)


class StockTransferView(WarehouseRequiredMixin, FormView):
    template_name = 'inventory/movements/transfer.html'
    form_class = StockTransferForm
    success_url = reverse_lazy('inventory:movements')

    def form_valid(self, form):
        try:
            transfer_stock(user=self.request.user, **form.cleaned_data)
            messages.success(self.request, 'تم تحويل المخزون')
            return redirect(self.success_url)
        except ValidationError as exc:
            form.add_error(None, exc.message)
            return self.form_invalid(form)


class StockAdjustmentView(ManagerRequiredMixin, FormView):
    template_name = 'inventory/movements/adjustment.html'
    form_class = StockAdjustmentForm
    success_url = reverse_lazy('inventory:movements')

    def form_valid(self, form):
        try:
            adjust_stock(user=self.request.user, **form.cleaned_data)
            messages.success(self.request, 'تمت تسوية المخزون')
            return redirect(self.success_url)
        except ValidationError as exc:
            form.add_error(None, exc.message)
            return self.form_invalid(form)


@require_GET
def ajax_check_stock(request):
    variant_id = request.GET.get('variant_id')
    warehouse_id = request.GET.get('warehouse_id')
    stock = Stock.objects.filter(variant_id=variant_id, warehouse_id=warehouse_id).first()
    quantity = stock.quantity if stock else 0
    return JsonResponse({'success': True, 'message': 'تم جلب الكمية', 'data': {'quantity': quantity}})

# Create your views here.
