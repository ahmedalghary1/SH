from django.contrib import messages
from django.db.models import DecimalField, F, Max, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.utils import timezone
from django.utils.text import slugify
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView

from accounts.permissions import ManagerRequiredMixin, SalesRequiredMixin, sales_required
from config.delete_views import ManagerDeleteView
from config.exports import ExportListMixin, export_pdf_response, export_xlsx_response
from config.search import arabic_search_q
from finance.models import PaymentTransaction
from finance.services import build_customer_statement
from orders.models import Order, OrderItem
from returns.models import SalesReturn

from .forms import CustomerForm, CustomerInteractionForm, SimpleCustomerForm
from .models import Customer, CustomerInteraction
from .services import (
    get_crm_dashboard_context,
    get_customer_summary,
    get_customers_with_debt,
    get_due_followups,
    get_inactive_customers,
    get_open_complaints,
    get_top_customers,
    visible_customers_for_user,
)


class CustomerVisibilityMixin:
    def get_queryset(self):
        qs = super().get_queryset()
        return visible_customers_for_user(self.request.user, qs)


class SimpleCustomerListView(SalesRequiredMixin, ListView):
    model = Customer
    template_name = 'customers/simple_list.html'
    context_object_name = 'customers'
    paginate_by = 20

    def get_queryset(self):
        qs = Customer.objects.select_related('created_by', 'sales_representative').filter(is_active=True)
        qs = visible_customers_for_user(self.request.user, qs).annotate(
            total_purchases=Sum('order__total', filter=Q(order__status__in=[Order.STATUS_COMPLETED, Order.STATUS_PARTIALLY_RETURNED])),
            current_balance=F('opening_balance') + Coalesce(
                Sum('order__remaining_amount', filter=Q(order__status__in=[Order.STATUS_COMPLETED, Order.STATUS_PARTIALLY_RETURNED])),
                Value(0), output_field=DecimalField(max_digits=14, decimal_places=2),
            ),
            last_transaction_date=Max(
                'order__created_at',
                filter=~Q(order__status__in=[Order.STATUS_DRAFT, Order.STATUS_CANCELLED])
            ),
        )
        
        q = self.request.GET.get('q')
        customer_type = self.request.GET.get('type')
        debt = self.request.GET.get('debt')
        
        valid_types = {choice[0] for choice in Customer.CUSTOMER_TYPE_CHOICES}
        debt_order_statuses = [
            Order.STATUS_CONFIRMED,
            Order.STATUS_PREPARING,
            Order.STATUS_READY,
            Order.STATUS_COMPLETED,
            Order.STATUS_PARTIALLY_RETURNED,
        ]
        if q:
            qs = qs.filter(arabic_search_q(('name', 'phone', 'company_name', 'address'), q))
        if customer_type in valid_types:
            qs = qs.filter(customer_type=customer_type)
        if debt == 'yes':
            qs = qs.filter(Q(opening_balance__gt=0) | Q(order__remaining_amount__gt=0, order__status__in=debt_order_statuses))
        elif debt == 'no':
            qs = qs.exclude(Q(opening_balance__gt=0) | Q(order__remaining_amount__gt=0, order__status__in=debt_order_statuses))
        
        ordering = self.request.GET.get('sort')
        if ordering in {'balance', '-balance'}:
            qs = qs.order_by('current_balance' if ordering == 'balance' else '-current_balance', 'name')
        else:
            qs = qs.order_by('-created_at')
        return qs.distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['sort'] = self.request.GET.get('sort', '')
        return context


class CustomerListView(SalesRequiredMixin, ExportListMixin, ListView):
    model = Customer
    template_name = 'customers/list.html'
    context_object_name = 'customers'
    paginate_by = 20
    export_title = 'قائمة العملاء'
    export_filename = 'customers'
    export_columns = (
        ('اسم العميل', 'name'),
        ('نوع العميل', 'get_customer_type_display'),
        ('الهاتف', 'phone'),
        ('الشركة', 'company_name'),
        ('العنوان', 'address'),
        ('مسؤول المبيعات', 'sales_representative'),
        ('أضيف بواسطة', 'created_by'),
        ('تاريخ الإضافة', 'created_at'),
    )

    def get_queryset(self):
        qs = Customer.objects.select_related('created_by', 'sales_representative').filter(is_active=True)
        qs = visible_customers_for_user(self.request.user, qs).annotate(
            current_balance=F('opening_balance') + Coalesce(
                Sum('order__remaining_amount', filter=Q(order__status__in=[Order.STATUS_COMPLETED, Order.STATUS_PARTIALLY_RETURNED])),
                Value(0), output_field=DecimalField(max_digits=14, decimal_places=2),
            )
        )
        q = self.request.GET.get('q')
        customer_type = self.request.GET.get('type')
        valid_types = {choice[0] for choice in Customer.CUSTOMER_TYPE_CHOICES}
        if q:
            qs = qs.filter(arabic_search_q(('name', 'phone', 'company_name', 'address'), q))
        if customer_type in valid_types:
            qs = qs.filter(customer_type=customer_type)
        ordering = self.request.GET.get('sort')
        return qs.order_by('current_balance' if ordering == 'balance' else '-current_balance' if ordering == '-balance' else '-created_at')


class SimpleCustomerCreateView(SalesRequiredMixin, CreateView):
    model = Customer
    form_class = SimpleCustomerForm
    template_name = 'customers/simple_create.html'
    success_url = reverse_lazy('customers:simple_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        if self.request.user.is_sales and not form.instance.sales_representative_id:
            form.instance.sales_representative = self.request.user
        messages.success(self.request, 'تم إضافة العميل')
        return super().form_valid(form)


class CustomerCreateView(SalesRequiredMixin, CreateView):
    model = Customer
    form_class = CustomerForm
    template_name = 'customers/create.html'
    success_url = reverse_lazy('customers:list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        if self.request.user.is_sales and not form.instance.sales_representative_id:
            form.instance.sales_representative = self.request.user
        messages.success(self.request, 'تم إضافة العميل')
        return super().form_valid(form)


class CustomerUpdateView(CustomerVisibilityMixin, SalesRequiredMixin, UpdateView):
    model = Customer
    form_class = CustomerForm
    template_name = 'customers/update.html'
    success_url = reverse_lazy('customers:list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, 'تم تعديل العميل')
        return super().form_valid(form)


class CustomerDeleteView(ManagerDeleteView):
    model = Customer
    success_url = reverse_lazy('customers:list')
    success_message = 'تم حذف العميل'


class SimpleCustomerDetailView(CustomerVisibilityMixin, SalesRequiredMixin, DetailView):
    model = Customer
    template_name = 'customers/simple_detail.html'
    context_object_name = 'customer'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        customer = self.object
        
        # Get summary
        summary = get_customer_summary(customer)
        
        # Get orders
        orders = Order.objects.filter(customer=customer).exclude(
            status__in=[Order.STATUS_DRAFT, Order.STATUS_CANCELLED, Order.STATUS_RETURNED],
        ).select_related('created_by').order_by('-created_at')
        
        # Get returns
        returns = SalesReturn.objects.filter(customer=customer).select_related('created_by').order_by('-created_at')
        
        # Get payments
        payments = PaymentTransaction.objects.filter(
            related_customer=customer,
            direction=PaymentTransaction.DIRECTION_IN,
            transaction_type__in=[PaymentTransaction.TYPE_CUSTOMER_PAYMENT, PaymentTransaction.TYPE_SALES_REP_COLLECTION],
        ).select_related('cash_account', 'created_by').order_by('-created_at')
        
        # Calculate total returns
        total_returns = returns.filter(status=SalesReturn.STATUS_COMPLETED).aggregate(v=Sum('refund_amount'))['v'] or 0
        
        # Get last payment
        last_payment = payments.first()
        
        # Generate statement
        statement_data = build_customer_statement(customer)
        
        context.update({
            'summary': {
                'total_purchases': summary['total_purchases'],
                'total_paid': summary['total_paid'],
                'total_remaining': statement_data['current_balance'],
                'total_returns': total_returns,
                'last_order': summary['last_order'],
                'last_payment': last_payment,
            },
            'orders': orders[:20],
            'returns': returns[:20],
            'payments': payments[:20],
            'statement': statement_data['entries'],
        })
        return context

    def _generate_statement(self, customer, orders, returns, payments):
        from decimal import Decimal
        statement = []
        
        # Opening balance
        if customer.opening_balance and customer.opening_balance > 0:
            statement.append({
                'date': customer.created_at,
                'type': 'رصيد افتتاحي',
                'description': 'رصيد افتتاحي',
                'debit': customer.opening_balance,
                'credit': '',
                'balance': customer.opening_balance,
            })
        
        # Combine all transactions
        transactions = []
        for order in orders:
            transactions.append({
                'date': order.created_at,
                'type': 'فاتورة بيع',
                'description': f'فاتورة {order.order_number}',
                'debit': order.total,
                'credit': '',
                'order': order,
            })
        
        for ret in returns.filter(status=SalesReturn.STATUS_COMPLETED):
            transactions.append({
                'date': ret.created_at,
                'type': 'مرتجع',
                'description': f'مرتجع {ret.id}',
                'debit': '',
                'credit': ret.refund_amount,
                'return': ret,
            })
        
        for payment in payments:
            transactions.append({
                'date': payment.created_at,
                'type': 'تحصيل',
                'description': payment.notes or 'تحصيل',
                'debit': '',
                'credit': payment.amount,
                'payment': payment,
            })
        
        # Sort by date
        transactions.sort(key=lambda x: x['date'])
        
        # Calculate running balance
        balance = customer.opening_balance or Decimal('0')
        for trans in transactions:
            if trans['debit']:
                balance += trans['debit']
            if trans['credit']:
                balance -= trans['credit']
            trans['balance'] = balance
            statement.append(trans)
        
        return statement


class CustomerDetailView(CustomerVisibilityMixin, SalesRequiredMixin, DetailView):
    model = Customer
    template_name = 'customers/detail.html'
    context_object_name = 'customer'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        orders = Order.objects.filter(customer=self.object).exclude(
            status__in=[Order.STATUS_DRAFT, Order.STATUS_CANCELLED, Order.STATUS_RETURNED],
        ).select_related('created_by').prefetch_related('items__variant__product', 'items__variant__color', 'items__variant__size')
        order_items = OrderItem.objects.filter(order__customer=self.object).exclude(
            order__status__in=[Order.STATUS_DRAFT, Order.STATUS_CANCELLED, Order.STATUS_RETURNED],
        ).select_related('order__created_by', 'variant__product', 'variant__color', 'variant__size').order_by('-order__created_at')
        context['summary'] = get_customer_summary(self.object)
        context['orders'] = orders.order_by('-created_at')
        context['movement_rows'] = order_items[:100]
        context['total_discounts'] = orders.aggregate(total=Sum('discount'))['total'] or 0
        return context


class CRMDashboardView(SalesRequiredMixin, TemplateView):
    template_name = 'customers/crm/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(get_crm_dashboard_context(user=self.request.user))
        return context


class CustomerCRMDetailView(CustomerVisibilityMixin, SalesRequiredMixin, DetailView):
    model = Customer
    template_name = 'customers/crm/detail.html'
    context_object_name = 'customer'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        customer = self.object
        context['summary'] = get_customer_summary(customer)
        context['orders'] = Order.objects.filter(customer=customer).order_by('-created_at')[:20]
        context['payments'] = PaymentTransaction.objects.filter(related_customer=customer).select_related('cash_account').order_by('-created_at')[:20]
        context['returns'] = SalesReturn.objects.filter(customer=customer).order_by('-created_at')[:20]
        context['interactions'] = customer.interactions.select_related('created_by')[:20]
        return context


class CustomerInteractionListView(SalesRequiredMixin, ListView):
    model = CustomerInteraction
    template_name = 'customers/crm/interactions.html'
    context_object_name = 'interactions'
    paginate_by = 30

    def dispatch(self, request, *args, **kwargs):
        self.customer = get_object_or_404(visible_customers_for_user(request.user, Customer.objects.all()), pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return self.customer.interactions.select_related('created_by').order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['customer'] = self.customer
        return context


class CustomerInteractionCreateView(SalesRequiredMixin, CreateView):
    model = CustomerInteraction
    form_class = CustomerInteractionForm
    template_name = 'customers/crm/interaction_form.html'

    def dispatch(self, request, *args, **kwargs):
        self.customer = get_object_or_404(visible_customers_for_user(request.user, Customer.objects.all()), pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.customer = self.customer
        form.instance.created_by = self.request.user
        messages.success(self.request, 'تم تسجيل التفاعل')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('customers:crm_detail', kwargs={'pk': self.customer.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['customer'] = self.customer
        return context


class CustomerInteractionUpdateView(SalesRequiredMixin, UpdateView):
    model = CustomerInteraction
    form_class = CustomerInteractionForm
    template_name = 'customers/crm/interaction_form.html'
    pk_url_kwarg = 'interaction_id'

    def dispatch(self, request, *args, **kwargs):
        self.customer = get_object_or_404(visible_customers_for_user(request.user, Customer.objects.all()), pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return CustomerInteraction.objects.filter(customer=self.customer)

    def form_valid(self, form):
        messages.success(self.request, 'تم تعديل التفاعل')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('customers:crm_detail', kwargs={'pk': self.customer.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['customer'] = self.customer
        return context


class CustomerInteractionDeleteView(ManagerDeleteView):
    model = CustomerInteraction
    pk_url_kwarg = 'interaction_id'
    success_message = 'تم حذف المتابعة'

    def dispatch(self, request, *args, **kwargs):
        self.customer = get_object_or_404(visible_customers_for_user(request.user, Customer.objects.all()), pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return CustomerInteraction.objects.filter(customer=self.customer)

    def get_success_url(self):
        return reverse('customers:crm_detail', kwargs={'pk': self.customer.pk})


class TodayInteractionsView(SalesRequiredMixin, ListView):
    model = CustomerInteraction
    template_name = 'customers/crm/today.html'
    context_object_name = 'interactions'
    paginate_by = 30

    def get_queryset(self):
        return get_due_followups(user=self.request.user)


class TopCustomersReportView(SalesRequiredMixin, TemplateView):
    template_name = 'customers/reports/top_customers.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['customers'] = get_top_customers(50, user=self.request.user)
        return context


class InactiveCustomersReportView(SalesRequiredMixin, ListView):
    model = Customer
    template_name = 'customers/reports/inactive.html'
    context_object_name = 'customers'
    paginate_by = 30

    def get_queryset(self):
        days = int(self.request.GET.get('days') or 90)
        self.days = days
        return get_inactive_customers(days, user=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['days'] = getattr(self, 'days', 90)
        return context


class DebtorsReportView(SalesRequiredMixin, ListView):
    model = Customer
    template_name = 'customers/reports/debtors.html'
    context_object_name = 'customers'
    paginate_by = 30

    def get_queryset(self):
        return get_customers_with_debt(user=self.request.user)


class ComplaintsReportView(SalesRequiredMixin, ListView):
    model = CustomerInteraction
    template_name = 'customers/reports/complaints.html'
    context_object_name = 'complaints'
    paginate_by = 30

    def get_queryset(self):
        return get_open_complaints(user=self.request.user)


@require_POST
@sales_required
def complete_interaction(request, pk, interaction_id):
    visible_customers = visible_customers_for_user(request.user, Customer.objects.all())
    interaction = get_object_or_404(CustomerInteraction, pk=interaction_id, customer__in=visible_customers, customer_id=pk)
    interaction.is_completed = True
    interaction.save(update_fields=['is_completed', 'updated_at'])
    messages.success(request, 'تم إكمال المتابعة')
    return redirect('customers:crm_detail', pk=pk)


@require_GET
@sales_required
def ajax_search_customers(request):
    q = request.GET.get('q', '').strip()
    qs = visible_customers_for_user(request.user, Customer.objects.filter(is_active=True))
    if q:
        qs = qs.filter(arabic_search_q(('name', 'phone', 'company_name', 'address'), q))
    data = [
        {'id': c.id, 'name': c.name, 'phone': c.phone, 'customer_type': c.customer_type, 'company_name': c.company_name or ''}
        for c in qs[:12]
    ]
    return JsonResponse({'success': True, 'message': 'تم جلب العملاء', 'data': data})


@require_POST
@sales_required
def ajax_quick_create_customer(request):
    form = SimpleCustomerForm(request.POST, user=request.user)
    if form.is_valid():
        customer = form.save(commit=False)
        customer.created_by = request.user
        if request.user.is_sales and not customer.sales_representative_id:
            customer.sales_representative = request.user
        customer.save()
        return JsonResponse({
            'success': True,
            'message': 'تم إضافة العميل',
            'data': {'id': customer.id, 'name': customer.name, 'phone': customer.phone, 'customer_type': customer.customer_type},
        })
    return JsonResponse({'success': False, 'message': 'بيانات العميل غير صحيحة', 'errors': form.errors}, status=400)


@require_GET
@sales_required
def export_customer_statement(request, pk, export_format):
    customer = get_object_or_404(visible_customers_for_user(request.user, Customer.objects.all()), pk=pk)
    statement = build_customer_statement(customer)
    headers = ['التاريخ والوقت', 'نوع الحركة', 'رقم المستند', 'البيان', 'عليه', 'له', 'الرصيد']
    rows = []
    for entry in statement['entries']:
        document = getattr(entry.get('order'), 'order_number', '') or getattr(entry.get('sales_return'), 'pk', '') or getattr(entry.get('transaction'), 'reference', '')
        rows.append([str(entry.get('date') or ''), entry.get('type'), document, entry.get('description'), entry.get('debit'), entry.get('credit'), entry.get('balance')])
    rows.append(['', '', '', 'الإجماليات', statement['total_debit'], statement['total_credit'], statement['current_balance']])
    safe_name = slugify(customer.name, allow_unicode=True).replace('/', '-') or f'customer-{customer.pk}'
    filename = f'customer-statement-{safe_name}-{timezone.localdate():%Y-%m-%d}'
    metadata = [('اسم العميل', customer.name), ('الهاتف', customer.phone or ''), ('العنوان', customer.address or ''), ('الرصيد الافتتاحي', statement['opening_balance'])]
    if export_format == 'pdf':
        return export_pdf_response(filename=filename, title=f'كشف حساب عميل - {customer.name}', headers=headers, rows=rows)
    if export_format == 'xlsx':
        return export_xlsx_response(filename=filename, title='كشف حساب عميل', headers=headers, rows=rows, metadata=metadata)
    return JsonResponse({'success': False, 'message': 'صيغة تصدير غير مدعومة'}, status=400)
