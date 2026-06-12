from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import FormView, ListView, TemplateView

from accounts.permissions import ManagerRequiredMixin, RoleRequiredMixin, WarehouseRequiredMixin
from config.delete_views import ManagerDeleteView
from config.exports import ExportListMixin

from .forms import AssignStockForm, AssignmentActionForm, SalesRepCollectionForm, SalesRepHandoverForm, SalesRepStatementForm
from .models import SalesRepCollection, SalesRepStockAssignment
from .services import (
    assign_stock_to_sales_rep,
    get_sales_rep_statement,
    handover_sales_rep_cash,
    record_sales_rep_collection,
    record_sales_rep_sale,
    return_stock_from_sales_rep,
)


class SalesRepDashboardView(RoleRequiredMixin, TemplateView):
    allowed_roles = ('manager', 'sales', 'warehouse')
    template_name = 'sales_reps/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        assignments = SalesRepStockAssignment.objects.select_related('sales_rep', 'product_variant__product', 'source_warehouse')
        collections = SalesRepCollection.objects.select_related('sales_rep', 'customer', 'order', 'cash_account')
        if self.request.user.role == 'sales' and not self.request.user.is_superuser:
            assignments = assignments.filter(sales_rep=self.request.user)
            collections = collections.filter(sales_rep=self.request.user)
        context['assignments'] = assignments.order_by('-created_at')[:30]
        context['collections'] = collections.order_by('-created_at')[:30]
        return context


class AssignStockView(WarehouseRequiredMixin, FormView):
    template_name = 'sales_reps/assign.html'
    form_class = AssignStockForm

    def form_valid(self, form):
        try:
            assign_stock_to_sales_rep(assigned_by=self.request.user, **form.cleaned_data)
            messages.success(self.request, 'تم تسليم البضاعة للمندوب')
            return redirect('sales_reps:dashboard')
        except ValidationError as exc:
            form.add_error(None, exc.message)
            return self.form_invalid(form)


class ReturnStockView(WarehouseRequiredMixin, FormView):
    template_name = 'sales_reps/return_stock.html'
    form_class = AssignmentActionForm

    def form_valid(self, form):
        try:
            return_stock_from_sales_rep(user=self.request.user, **form.cleaned_data)
            messages.success(self.request, 'تم تسجيل رجوع بضاعة من المندوب')
            return redirect('sales_reps:dashboard')
        except ValidationError as exc:
            form.add_error(None, exc.message)
            return self.form_invalid(form)


class RecordSaleView(WarehouseRequiredMixin, FormView):
    template_name = 'sales_reps/sale.html'
    form_class = AssignmentActionForm

    def form_valid(self, form):
        try:
            record_sales_rep_sale(user=self.request.user, **form.cleaned_data)
            messages.success(self.request, 'تم تسجيل بيع من عهدة المندوب')
            return redirect('sales_reps:dashboard')
        except ValidationError as exc:
            form.add_error(None, exc.message)
            return self.form_invalid(form)


class CollectionCreateView(ManagerRequiredMixin, FormView):
    template_name = 'sales_reps/collection.html'
    form_class = SalesRepCollectionForm

    def form_valid(self, form):
        try:
            record_sales_rep_collection(user=self.request.user, **form.cleaned_data)
            messages.success(self.request, 'تم تسجيل تحصيل المندوب')
            return redirect('sales_reps:dashboard')
        except ValidationError as exc:
            form.add_error(None, exc.message)
            return self.form_invalid(form)


class HandoverCreateView(ManagerRequiredMixin, FormView):
    template_name = 'sales_reps/handover.html'
    form_class = SalesRepHandoverForm

    def form_valid(self, form):
        try:
            handover_sales_rep_cash(user=self.request.user, **form.cleaned_data)
            messages.success(self.request, 'تم تسليم نقدية المندوب للإدارة')
            return redirect('sales_reps:dashboard')
        except ValidationError as exc:
            form.add_error(None, exc.message)
            return self.form_invalid(form)


class StatementView(RoleRequiredMixin, FormView):
    allowed_roles = ('manager', 'sales', 'warehouse')
    template_name = 'sales_reps/statement.html'
    form_class = SalesRepStatementForm

    def form_valid(self, form):
        sales_rep = form.cleaned_data['sales_rep']
        if self.request.user.role == 'sales' and sales_rep != self.request.user and not self.request.user.is_superuser:
            form.add_error('sales_rep', 'يمكنك عرض كشف عهدتك فقط')
            return self.form_invalid(form)
        statement = get_sales_rep_statement(sales_rep)
        return self.render_to_response(self.get_context_data(form=form, sales_rep=sales_rep, statement=statement))


class AssignmentListView(RoleRequiredMixin, ExportListMixin, ListView):
    allowed_roles = ('manager', 'sales', 'warehouse')
    model = SalesRepStockAssignment
    template_name = 'sales_reps/assignments.html'
    context_object_name = 'assignments'
    paginate_by = 30
    export_title = 'قائمة عهد المناديب'
    export_filename = 'sales-rep-assignments'
    export_columns = (
        ('المندوب', 'sales_rep'),
        ('الصنف', 'product_variant'),
        ('المخزن', 'source_warehouse'),
        ('المسلم', 'quantity_assigned'),
        ('المباع', 'quantity_sold'),
        ('الراجع', 'quantity_returned'),
        ('المتبقي', 'quantity_remaining'),
        ('التاريخ', 'created_at'),
    )

    def get_queryset(self):
        qs = SalesRepStockAssignment.objects.select_related('sales_rep', 'product_variant__product', 'source_warehouse').order_by('-created_at')
        if self.request.user.role == 'sales' and not self.request.user.is_superuser:
            qs = qs.filter(sales_rep=self.request.user)
        return qs


class SalesRepStockAssignmentDeleteView(ManagerDeleteView):
    model = SalesRepStockAssignment
    success_url = reverse_lazy('sales_reps:assignments')
    success_message = 'تم حذف عهدة المندوب'


class SalesRepCollectionDeleteView(ManagerDeleteView):
    model = SalesRepCollection
    success_url = reverse_lazy('sales_reps:dashboard')
    success_message = 'تم حذف تحصيل المندوب'
