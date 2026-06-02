from django.contrib import messages
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from accounts.permissions import SalesRequiredMixin, sales_required

from .forms import CustomerForm
from .models import Customer


class CustomerListView(SalesRequiredMixin, ListView):
    model = Customer
    template_name = 'customers/list.html'
    context_object_name = 'customers'
    paginate_by = 20

    def get_queryset(self):
        qs = Customer.objects.select_related('created_by').filter(is_active=True)
        q = self.request.GET.get('q')
        customer_type = self.request.GET.get('type')
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(phone__icontains=q) | Q(company_name__icontains=q))
        if customer_type in {'b2b', 'b2c'}:
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


@require_GET
@sales_required
def ajax_search_customers(request):
    q = request.GET.get('q', '').strip()
    qs = Customer.objects.filter(is_active=True)
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(phone__icontains=q) | Q(company_name__icontains=q))
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

# Create your views here.
