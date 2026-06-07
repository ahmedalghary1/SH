from django.contrib import messages
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView

from accounts.permissions import SalesRequiredMixin, sales_required
from config.exports import ExportListMixin
from config.search import arabic_search_q
from finance.models import PaymentTransaction
from orders.models import Order, OrderItem
from returns.models import SalesReturn

from .forms import CustomerForm, CustomerInteractionForm
from .models import Customer, CustomerInteraction
from .services import (
    get_crm_dashboard_context,
    get_customer_summary,
    get_customers_with_debt,
    get_due_followups,
    get_inactive_customers,
    get_open_complaints,
    get_top_customers,
)


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
        ('المسؤول', 'created_by'),
        ('تاريخ الإضافة', 'created_at'),
    )

    def get_queryset(self):
        qs = Customer.objects.select_related('created_by').filter(is_active=True)
        q = self.request.GET.get('q')
        customer_type = self.request.GET.get('type')
        valid_types = {choice[0] for choice in Customer.CUSTOMER_TYPE_CHOICES}
        if q:
            qs = qs.filter(arabic_search_q(('name', 'phone', 'company_name'), q))
        if customer_type in valid_types:
            qs = qs.filter(customer_type=customer_type)
        return qs.order_by('-created_at')


class CustomerCreateView(SalesRequiredMixin, CreateView):
    model = Customer
    form_class = CustomerForm
    template_name = 'customers/create.html'
    success_url = reverse_lazy('customers:list')

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, 'تم إضافة العميل')
        return super().form_valid(form)


class CustomerUpdateView(SalesRequiredMixin, UpdateView):
    model = Customer
    form_class = CustomerForm
    template_name = 'customers/update.html'
    success_url = reverse_lazy('customers:list')

    def form_valid(self, form):
        messages.success(self.request, 'تم تعديل العميل')
        return super().form_valid(form)


class CustomerDetailView(SalesRequiredMixin, DetailView):
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
        context.update(get_crm_dashboard_context())
        return context


class CustomerCRMDetailView(SalesRequiredMixin, DetailView):
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
        self.customer = get_object_or_404(Customer, pk=kwargs['pk'])
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
        self.customer = get_object_or_404(Customer, pk=kwargs['pk'])
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
        self.customer = get_object_or_404(Customer, pk=kwargs['pk'])
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


class TodayInteractionsView(SalesRequiredMixin, ListView):
    model = CustomerInteraction
    template_name = 'customers/crm/today.html'
    context_object_name = 'interactions'
    paginate_by = 30

    def get_queryset(self):
        return get_due_followups()


class TopCustomersReportView(SalesRequiredMixin, TemplateView):
    template_name = 'customers/reports/top_customers.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['customers'] = get_top_customers(50)
        return context


class InactiveCustomersReportView(SalesRequiredMixin, ListView):
    model = Customer
    template_name = 'customers/reports/inactive.html'
    context_object_name = 'customers'
    paginate_by = 30

    def get_queryset(self):
        days = int(self.request.GET.get('days') or 90)
        self.days = days
        return get_inactive_customers(days)

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
        return get_customers_with_debt()


class ComplaintsReportView(SalesRequiredMixin, ListView):
    model = CustomerInteraction
    template_name = 'customers/reports/complaints.html'
    context_object_name = 'complaints'
    paginate_by = 30

    def get_queryset(self):
        return get_open_complaints()


@require_POST
@sales_required
def complete_interaction(request, pk, interaction_id):
    interaction = get_object_or_404(CustomerInteraction, pk=interaction_id, customer_id=pk)
    interaction.is_completed = True
    interaction.save(update_fields=['is_completed', 'updated_at'])
    messages.success(request, 'تم إكمال المتابعة')
    return redirect('customers:crm_detail', pk=pk)


@require_GET
@sales_required
def ajax_search_customers(request):
    q = request.GET.get('q', '').strip()
    qs = Customer.objects.filter(is_active=True)
    if q:
        qs = qs.filter(arabic_search_q(('name', 'phone', 'company_name'), q))
    data = [
        {'id': c.id, 'name': c.name, 'phone': c.phone, 'customer_type': c.customer_type, 'company_name': c.company_name or ''}
        for c in qs[:12]
    ]
    return JsonResponse({'success': True, 'message': 'تم جلب العملاء', 'data': data})


@require_POST
@sales_required
def ajax_quick_create_customer(request):
    form = CustomerForm(request.POST)
    if form.is_valid():
        customer = form.save(commit=False)
        customer.created_by = request.user
        customer.save()
        return JsonResponse({
            'success': True,
            'message': 'تم إضافة العميل',
            'data': {'id': customer.id, 'name': customer.name, 'phone': customer.phone, 'customer_type': customer.customer_type},
        })
    return JsonResponse({'success': False, 'message': 'بيانات العميل غير صحيحة', 'errors': form.errors}, status=400)
