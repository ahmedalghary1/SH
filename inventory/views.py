from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import F, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.decorators.http import require_GET
from django.views.generic import CreateView, FormView, ListView

from accounts.permissions import ManagerRequiredMixin, RoleRequiredMixin, WarehouseRequiredMixin, can_view_costs, role_required
from config.exports import ExportListMixin
from config.search import arabic_search_q
from products.models import ProductVariant

from .forms import RepresentativeIssueForm, RepresentativeReturnForm, StockAdjustmentForm, StockMovementForm, StockTransferForm, WarehouseForm
from .models import Stock, StockMovement, Warehouse
from .services import adjust_stock, stock_in, stock_out, transfer_stock


class WarehouseListView(RoleRequiredMixin, ExportListMixin, ListView):
    allowed_roles = ('manager', 'warehouse')
    model = Warehouse
    template_name = 'inventory/warehouses/list.html'
    context_object_name = 'warehouses'
    paginate_by = 20
    export_title = 'قائمة المخازن'
    export_filename = 'warehouses'
    export_columns = (
        ('اسم المخزن', 'name'),
        ('النوع', 'get_warehouse_type_display'),
        ('المسؤول', 'assigned_user'),
        ('العنوان', 'address'),
        ('الحالة', lambda warehouse: 'نشط' if warehouse.is_active else 'متوقف'),
    )

    def get_queryset(self):
        return Warehouse.objects.select_related('assigned_user').order_by('warehouse_type', 'name')


class WarehouseCreateView(ManagerRequiredMixin, CreateView):
    model = Warehouse
    form_class = WarehouseForm
    template_name = 'inventory/warehouses/create.html'
    success_url = reverse_lazy('inventory:warehouses')


class StockListView(RoleRequiredMixin, ExportListMixin, ListView):
    allowed_roles = ('manager', 'sales', 'warehouse')
    model = Stock
    template_name = 'inventory/stock/list.html'
    context_object_name = 'stocks'
    paginate_by = 30
    export_title = 'قائمة المخزون'
    export_filename = 'stock'
    
    def get_export_columns(self):
        base_columns = [
            ('المخزن', 'warehouse.name'),
            ('المنتج', 'variant.product.name'),
            ('كود المنتج', 'variant.product.sku'),
            ('كود اللون/المقاس', 'variant.variant_sku'),
            ('التصنيف', 'variant.product.category'),
            ('اللون', 'variant.color'),
            ('المقاس', 'variant.size'),
            ('سعر البيع', 'variant.sale_price'),
            ('الكمية', 'quantity'),
            ('الحد الأدنى', 'min_quantity'),
            ('تنبيه', lambda stock: 'منخفض' if stock.is_low else 'جيد'),
        ]
        if can_view_costs(self.request.user):
            base_columns.insert(7, ('سعر الشراء', 'variant.cost_price'))
        return base_columns

    def get_allowed_warehouses(self):
        qs = Warehouse.objects.filter(is_active=True)
        if self.request.user.role == 'sales' and not self.request.user.is_superuser:
            qs = qs.filter(
                assigned_user=self.request.user,
                warehouse_type=Warehouse.TYPE_REPRESENTATIVE,
            )
        return qs.order_by('warehouse_type', 'name')

    def get_queryset(self):
        qs = Stock.objects.select_related(
            'warehouse',
            'variant__product',
            'variant__product__category',
            'variant__color',
            'variant__size',
        )
        if self.request.user.role == 'sales' and not self.request.user.is_superuser:
            qs = qs.filter(warehouse__in=self.get_allowed_warehouses())
        warehouse_id = self.request.GET.get('warehouse')
        if warehouse_id:
            if warehouse_id.isdigit() and self.get_allowed_warehouses().filter(pk=warehouse_id).exists():
                qs = qs.filter(warehouse_id=warehouse_id)
            else:
                qs = qs.none()
        q = self.request.GET.get('q')
        if q:
            qs = qs.filter(arabic_search_q((
                'variant__product__name',
                'variant__product__sku',
                'variant__product__category__name',
                'variant__variant_sku',
                'variant__barcode',
            ), q))
        low = self.request.GET.get('low')
        if low:
            qs = qs.filter(quantity__lte=F('min_quantity'))
        return qs.order_by('warehouse__name', 'variant__product__name', 'variant__color__name', 'variant__size__sort_order')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        pagination_params = self.request.GET.copy()
        pagination_params.pop('page', None)
        context['warehouses'] = self.get_allowed_warehouses()
        context['selected_warehouse_id'] = self.request.GET.get('warehouse', '')
        context['search_query'] = self.request.GET.get('q', '')
        context['low_only'] = self.request.GET.get('low', '')
        context['pagination_query'] = pagination_params.urlencode()
        context['can_view_costs'] = can_view_costs(self.request.user)
        return context


class StockMovementListView(RoleRequiredMixin, ExportListMixin, ListView):
    allowed_roles = ('manager', 'warehouse')
    model = StockMovement
    template_name = 'inventory/movements/list.html'
    context_object_name = 'movements'
    paginate_by = 30
    export_title = 'قائمة الحركات المخزنية'
    export_filename = 'stock-movements'
    export_columns = (
        ('التاريخ', 'created_at'),
        ('النوع', 'get_movement_type_display'),
        ('المنتج', 'variant.product.name'),
        ('الكود', 'variant.variant_sku'),
        ('من مخزن', 'from_warehouse'),
        ('إلى مخزن', 'to_warehouse'),
        ('الكمية', 'quantity'),
        ('الموظف', 'created_by'),
        ('ملاحظات', 'note'),
    )

    def get_queryset(self):
        allowed_types = [StockMovement.TYPE_TRANSFER]
        return StockMovement.objects.select_related(
            'variant__product', 'variant__color', 'variant__size', 'from_warehouse', 'to_warehouse', 'created_by',
        ).filter(movement_type__in=allowed_types).order_by('-created_at')


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

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields['variant'].widget.attrs.update({
            'data-stock-filter-target': 'id_warehouse',
            'data-stock-filter-scope': 'all',
        })
        return form

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


class RepresentativeIssueView(WarehouseRequiredMixin, FormView):
    template_name = 'inventory/movements/representative_issue.html'
    form_class = RepresentativeIssueForm
    success_url = reverse_lazy('inventory:movements')

    def form_valid(self, form):
        representative = form.cleaned_data['representative']
        rep_warehouse, _ = Warehouse.objects.get_or_create(
            warehouse_type=Warehouse.TYPE_REPRESENTATIVE,
            assigned_user=representative,
            defaults={'name': f'عهدة {representative.get_full_name() or representative.username}', 'is_active': True},
        )
        try:
            transfer_stock(
                user=self.request.user,
                variant=form.cleaned_data['variant'],
                from_warehouse=form.cleaned_data['from_warehouse'],
                to_warehouse=rep_warehouse,
                quantity=form.cleaned_data['quantity'],
                note=form.cleaned_data.get('note') or 'تسليم كمية للمندوب',
            )
            messages.success(self.request, 'تم تسليم الكمية للمندوب')
            return redirect(self.success_url)
        except ValidationError as exc:
            form.add_error(None, exc.message)
            return self.form_invalid(form)


class RepresentativeReturnView(WarehouseRequiredMixin, FormView):
    template_name = 'inventory/movements/representative_return.html'
    form_class = RepresentativeReturnForm
    success_url = reverse_lazy('inventory:movements')

    def form_valid(self, form):
        rep_warehouse = Warehouse.objects.filter(
            warehouse_type=Warehouse.TYPE_REPRESENTATIVE,
            assigned_user=form.cleaned_data['representative'],
            is_active=True,
        ).first()
        if not rep_warehouse:
            form.add_error('representative', 'لا توجد عهدة مخزون لهذا المندوب')
            return self.form_invalid(form)
        try:
            transfer_stock(
                user=self.request.user,
                variant=form.cleaned_data['variant'],
                from_warehouse=rep_warehouse,
                to_warehouse=form.cleaned_data['to_warehouse'],
                quantity=form.cleaned_data['quantity'],
                note=form.cleaned_data.get('note') or 'إرجاع كمية غير مباعة من المندوب',
            )
            messages.success(self.request, 'تم استلام الكمية المرتجعة من المندوب')
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
@role_required('manager', 'sales', 'warehouse')
def ajax_check_stock(request):
    variant_id = request.GET.get('variant_id')
    warehouse_id = request.GET.get('warehouse_id')
    stock = Stock.objects.filter(variant_id=variant_id, warehouse_id=warehouse_id).first()
    quantity = stock.quantity if stock else 0
    return JsonResponse({'success': True, 'message': 'تم جلب الكمية', 'data': {'quantity': quantity}})

@require_GET
@role_required('manager', 'sales', 'warehouse')
def ajax_variant_warehouses(request):
    variant_id = request.GET.get('variant_id')
    scope = request.GET.get('scope', 'all')
    stocks = Stock.objects.filter(
        variant_id=variant_id,
        quantity__gt=0,
        warehouse__is_active=True,
    ).select_related('warehouse')
    if scope == 'non_representative':
        stocks = stocks.exclude(warehouse__warehouse_type=Warehouse.TYPE_REPRESENTATIVE)
    elif scope == 'representative':
        stocks = stocks.filter(warehouse__warehouse_type=Warehouse.TYPE_REPRESENTATIVE)
    if request.user.role == 'sales' and not request.user.is_superuser:
        stocks = stocks.filter(
            warehouse__assigned_user=request.user,
            warehouse__warehouse_type=Warehouse.TYPE_REPRESENTATIVE,
        )
    data = [
        {
            'warehouse_id': stock.warehouse_id,
            'warehouse_name': stock.warehouse.name,
            'quantity': stock.quantity,
        }
        for stock in stocks.order_by('warehouse__name')
    ]
    return JsonResponse({'success': True, 'message': 'تم جلب المخازن', 'data': {'warehouses': data}})


# Create your views here.
