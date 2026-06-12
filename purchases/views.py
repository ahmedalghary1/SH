from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, FormView, ListView, TemplateView, UpdateView, View

from accounts.permissions import ManagerRequiredMixin, RoleRequiredMixin, WarehouseRequiredMixin, can_view_costs
from config.delete_views import ManagerDeleteView
from config.exports import ExportListMixin
from config.search import arabic_search_q
from finance.models import PaymentTransaction

from .forms import PurchaseOrderForm, PurchaseReceiveForm, SupplierForm, SupplierPaymentForm, SimpleSupplierForm
from .models import PurchaseOrder, Supplier
from .raw_material import RawMaterialPurchaseForm, record_raw_material_purchase
from .services import cancel_purchase_order, create_purchase_order, pay_supplier, receive_purchase_order_items


class SimpleSupplierListView(ManagerRequiredMixin, ListView):
    model = Supplier
    template_name = 'purchases/suppliers/simple_list.html'
    context_object_name = 'suppliers'
    paginate_by = 20

    def get_queryset(self):
        qs = Supplier.objects.filter(is_active=True).annotate(
            total_purchases=Sum('purchase_orders__total_amount', filter=Q(purchase_orders__status__in=[PurchaseOrder.STATUS_RECEIVED, PurchaseOrder.STATUS_PARTIALLY_RECEIVED])),
            total_paid=Sum('purchase_orders__paid_amount', filter=Q(purchase_orders__status__in=[PurchaseOrder.STATUS_RECEIVED, PurchaseOrder.STATUS_PARTIALLY_RECEIVED]))
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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for supplier in context['suppliers']:
            supplier.last_transaction_date = PurchaseOrder.objects.filter(supplier=supplier).exclude(
                status=PurchaseOrder.STATUS_CANCELLED
            ).order_by('-created_at').first()
            if supplier.last_transaction_date:
                supplier.last_transaction_date = supplier.last_transaction_date.created_at
        return context


class SimpleSupplierCreateView(ManagerRequiredMixin, CreateView):
    model = Supplier
    form_class = SimpleSupplierForm
    template_name = 'purchases/suppliers/simple_create.html'
    success_url = reverse_lazy('purchases:simple_supplier_list')

    def form_valid(self, form):
        form.instance.current_balance = form.cleaned_data.get('opening_balance') or 0
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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['can_view_costs'] = can_view_costs(self.request.user)
        return context


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


class PurchaseOrderDeleteView(ManagerDeleteView):
    model = PurchaseOrder
    success_url = reverse_lazy('purchases:orders')
    success_message = 'تم حذف أمر الشراء'


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
