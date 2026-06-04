from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import DetailView, FormView, ListView, TemplateView, View

from accounts.permissions import ManagerRequiredMixin, RoleRequiredMixin, SalesRequiredMixin

from .forms import CompleteReturnForm, ExchangeItemForm, ReturnItemForm, SalesReturnCreateForm
from .models import SalesReturn, SalesReturnItem
from .services import (
    add_exchange_item,
    add_return_item,
    approve_sales_return,
    complete_sales_return,
    create_sales_return,
)


class SalesReturnListView(RoleRequiredMixin, ListView):
    allowed_roles = ('manager', 'sales', 'warehouse')
    model = SalesReturn
    template_name = 'returns/list.html'
    context_object_name = 'returns'
    paginate_by = 20

    def get_queryset(self):
        qs = SalesReturn.objects.select_related('order', 'customer', 'created_by').order_by('-created_at')
        if self.request.user.role == 'sales' and not self.request.user.is_superuser:
            qs = qs.filter(created_by=self.request.user)
        status = self.request.GET.get('status')
        if status:
            qs = qs.filter(status=status)
        return qs


class SalesReturnCreateView(SalesRequiredMixin, FormView):
    template_name = 'returns/create.html'
    form_class = SalesReturnCreateForm

    def form_valid(self, form):
        try:
            sales_return = create_sales_return(
                order=form.cleaned_data['order'],
                return_type=form.cleaned_data['return_type'],
                reason=form.cleaned_data.get('reason') or '',
                user=self.request.user,
            )
            messages.success(self.request, 'تم إنشاء مسودة المرتجع')
            return redirect('returns:add_item', pk=sales_return.pk)
        except ValidationError as exc:
            form.add_error(None, exc.message)
            return self.form_invalid(form)


class SalesReturnDetailView(RoleRequiredMixin, DetailView):
    allowed_roles = ('manager', 'sales', 'warehouse')
    model = SalesReturn
    template_name = 'returns/detail.html'
    context_object_name = 'sales_return'

    def get_queryset(self):
        qs = SalesReturn.objects.select_related('order', 'customer', 'created_by', 'approved_by', 'completed_by').prefetch_related(
            'items__product_variant__product',
            'exchange_items__new_product_variant__product',
        )
        if self.request.user.role == 'sales' and not self.request.user.is_superuser:
            qs = qs.filter(created_by=self.request.user)
        return qs


class ReturnItemAddView(SalesRequiredMixin, FormView):
    template_name = 'returns/item_form.html'
    form_class = ReturnItemForm

    def dispatch(self, request, *args, **kwargs):
        self.sales_return = get_object_or_404(SalesReturn, pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['sales_return'] = self.sales_return
        return kwargs

    def form_valid(self, form):
        try:
            add_return_item(sales_return=self.sales_return, **form.cleaned_data)
            messages.success(self.request, 'تمت إضافة الصنف المرتجع')
            return redirect('returns:detail', pk=self.sales_return.pk)
        except ValidationError as exc:
            form.add_error(None, exc.message)
            return self.form_invalid(form)


class ExchangeItemAddView(SalesRequiredMixin, FormView):
    template_name = 'returns/exchange_form.html'
    form_class = ExchangeItemForm

    def dispatch(self, request, *args, **kwargs):
        self.sales_return = get_object_or_404(SalesReturn, pk=kwargs['pk'], return_type=SalesReturn.TYPE_EXCHANGE)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['sales_return'] = self.sales_return
        return kwargs

    def form_valid(self, form):
        try:
            add_exchange_item(sales_return=self.sales_return, **form.cleaned_data)
            messages.success(self.request, 'تمت إضافة صنف الاستبدال')
            return redirect('returns:detail', pk=self.sales_return.pk)
        except ValidationError as exc:
            form.add_error(None, exc.message)
            return self.form_invalid(form)


class SalesReturnApproveView(ManagerRequiredMixin, View):
    def post(self, request, pk):
        sales_return = get_object_or_404(SalesReturn, pk=pk)
        try:
            approve_sales_return(sales_return=sales_return, user=request.user)
            messages.success(request, 'تم اعتماد المرتجع')
        except ValidationError as exc:
            messages.error(request, exc.message)
        return redirect('returns:detail', pk=pk)


class SalesReturnCompleteView(ManagerRequiredMixin, FormView):
    template_name = 'returns/complete.html'
    form_class = CompleteReturnForm

    def dispatch(self, request, *args, **kwargs):
        self.sales_return = get_object_or_404(SalesReturn, pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        try:
            complete_sales_return(
                sales_return=self.sales_return,
                user=self.request.user,
                cash_account=form.cleaned_data.get('cash_account'),
            )
            messages.success(self.request, 'تم إكمال المرتجع وتسجيل آثاره')
            return redirect('returns:detail', pk=self.sales_return.pk)
        except ValidationError as exc:
            form.add_error(None, exc.message)
            return self.form_invalid(form)


class SalesReturnRejectView(ManagerRequiredMixin, View):
    def post(self, request, pk):
        sales_return = get_object_or_404(SalesReturn, pk=pk)
        if sales_return.status == SalesReturn.STATUS_DRAFT:
            sales_return.status = SalesReturn.STATUS_REJECTED
            sales_return.save(update_fields=['status'])
            messages.success(request, 'تم رفض المرتجع')
        else:
            messages.error(request, 'يمكن رفض المرتجع من حالة المسودة فقط')
        return redirect('returns:detail', pk=pk)


class ReturnReasonReportView(ManagerRequiredMixin, TemplateView):
    template_name = 'returns/reports/reasons.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['reasons'] = SalesReturn.objects.values('reason').annotate(count=Count('id'), total=Sum('refund_amount')).order_by('-count')
        return context


class ProductReturnReportView(ManagerRequiredMixin, TemplateView):
    template_name = 'returns/reports/products.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['items'] = SalesReturnItem.objects.filter(
            sales_return__status=SalesReturn.STATUS_COMPLETED,
        ).values('product_variant__product__name').annotate(qty=Sum('quantity'), total=Sum('refund_amount')).order_by('-qty')
        return context
