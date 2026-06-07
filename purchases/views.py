from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, FormView, ListView, TemplateView, UpdateView, View

from accounts.permissions import ManagerRequiredMixin, RoleRequiredMixin, WarehouseRequiredMixin
from config.exports import ExportListMixin
from config.search import arabic_search_q
from finance.models import PaymentTransaction

from .forms import PurchaseOrderForm, PurchaseReceiveForm, SupplierForm, SupplierPaymentForm
from .models import PurchaseOrder, Supplier
from .raw_material import RawMaterialPurchaseForm, record_raw_material_purchase
from .services import cancel_purchase_order, create_purchase_order, pay_supplier, receive_purchase_order_items


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
        form.instance.current_balance = form.cleaned_data.get('opening_balance') or 0
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
    export_title = 'قائمة أوامر الشراء'
    export_filename = 'purchase-orders'
    export_columns = (
        ('رقم أمر الشراء', 'purchase_number'),
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

    def form_valid(self, form):
        try:
            po = create_purchase_order(
                supplier=form.cleaned_data['supplier'],
                status=form.cleaned_data['status'],
                order_date=form.cleaned_data.get('order_date'),
                expected_date=form.cleaned_data.get('expected_date'),
                notes=form.cleaned_data.get('notes') or '',
                items=[{
                    'product_variant': form.cleaned_data['product_variant'],
                    'quantity': form.cleaned_data['quantity'],
                    'unit_cost': form.cleaned_data['unit_cost'],
                }],
                user=self.request.user,
            )
            messages.success(self.request, 'تم إنشاء أمر الشراء')
            return redirect('purchases:order_detail', pk=po.pk)
        except ValidationError as exc:
            form.add_error(None, exc.message)
            return self.form_invalid(form)


class PurchaseOrderDetailView(RoleRequiredMixin, DetailView):
    allowed_roles = ('manager', 'warehouse')
    model = PurchaseOrder
    template_name = 'purchases/orders/detail.html'
    context_object_name = 'purchase_order'

    def get_queryset(self):
        return PurchaseOrder.objects.select_related('supplier', 'created_by').prefetch_related('items__product_variant__product')


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


class PurchaseOrderCancelView(ManagerRequiredMixin, View):
    def post(self, request, pk):
        purchase_order = get_object_or_404(PurchaseOrder, pk=pk)
        try:
            cancel_purchase_order(purchase_order=purchase_order, user=request.user)
            messages.success(request, 'تم إلغاء أمر الشراء')
        except ValidationError as exc:
            messages.error(request, exc.message)
        return redirect('purchases:order_detail', pk=pk)


class PurchaseReportView(ManagerRequiredMixin, TemplateView):
    template_name = 'purchases/reports/purchases.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        orders = PurchaseOrder.objects.exclude(status=PurchaseOrder.STATUS_CANCELLED)
        context['orders'] = orders.select_related('supplier').order_by('-created_at')[:100]
        context['total_amount'] = orders.aggregate(v=Sum('total_amount'))['v'] or 0
        context['paid_amount'] = orders.aggregate(v=Sum('paid_amount'))['v'] or 0
        context['remaining_amount'] = orders.aggregate(v=Sum('remaining_amount'))['v'] or 0
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
