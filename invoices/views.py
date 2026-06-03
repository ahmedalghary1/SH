import csv

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import DetailView, ListView, View

from accounts.permissions import SalesRequiredMixin
from orders.models import Order
from settings_app.models import CompanySettings

from .forms import InvoiceFilterForm
from .models import Invoice
from .services import generate_invoice


class InvoiceContextMixin:
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['company_settings'] = CompanySettings.load()
        return context


class InvoiceDetailView(InvoiceContextMixin, SalesRequiredMixin, DetailView):
    model = Invoice
    template_name = 'invoices/detail.html'
    context_object_name = 'invoice'


class InvoiceListView(SalesRequiredMixin, ListView):
    model = Invoice
    template_name = 'invoices/list.html'
    context_object_name = 'invoices'
    paginate_by = 20

    def get_queryset(self):
        qs = Invoice.objects.select_related('order__customer', 'order__created_by').order_by('-issued_at')
        if self.request.user.role == 'sales' and not self.request.user.is_superuser:
            qs = qs.filter(order__created_by=self.request.user)
        self.filter_form = InvoiceFilterForm(self.request.GET)
        if self.filter_form.is_valid():
            date_from = self.filter_form.cleaned_data.get('date_from')
            date_to = self.filter_form.cleaned_data.get('date_to')
            if date_from:
                qs = qs.filter(issued_at__date__gte=date_from)
            if date_to:
                qs = qs.filter(issued_at__date__lte=date_to)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['filter_form'] = getattr(self, 'filter_form', InvoiceFilterForm(self.request.GET))
        return context


class InvoiceExportMixin:
    def get_filtered_invoices(self, request):
        qs = Invoice.objects.select_related('order__customer', 'order__created_by').order_by('-issued_at')
        if request.user.role == 'sales' and not request.user.is_superuser:
            qs = qs.filter(order__created_by=request.user)
        selected_ids = request.POST.getlist('invoice_ids') or request.GET.getlist('invoice_ids')
        if selected_ids:
            qs = qs.filter(pk__in=selected_ids)
        form = InvoiceFilterForm(request.POST or request.GET)
        if form.is_valid():
            date_from = form.cleaned_data.get('date_from')
            date_to = form.cleaned_data.get('date_to')
            if date_from:
                qs = qs.filter(issued_at__date__gte=date_from)
            if date_to:
                qs = qs.filter(issued_at__date__lte=date_to)
        return qs


class InvoiceExcelExportView(InvoiceExportMixin, SalesRequiredMixin, View):
    def dispatch(self, request, *args, **kwargs):
        self.request = request
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        return self.build_response(request)

    def post(self, request):
        return self.build_response(request)

    def build_response(self, request):
        response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
        response['Content-Disposition'] = 'attachment; filename=\"invoices.csv\"'
        response.write('\ufeff')
        writer = csv.writer(response)
        writer.writerow(['رقم الفاتورة', 'رقم الطلب', 'العميل', 'المندوب', 'طريقة الدفع', 'الإجمالي', 'المدفوع', 'المتبقي', 'التاريخ'])
        for invoice in self.get_filtered_invoices(request):
            writer.writerow([
                invoice.invoice_number,
                invoice.order.order_number,
                invoice.order.customer or '',
                invoice.order.created_by or '',
                invoice.order.get_payment_method_display(),
                invoice.order.total,
                invoice.order.paid_amount,
                invoice.order.remaining_amount,
                invoice.issued_at,
            ])
        return response


class InvoiceReportPrintView(InvoiceExportMixin, InvoiceContextMixin, SalesRequiredMixin, ListView):
    model = Invoice
    template_name = 'invoices/report_print.html'
    context_object_name = 'invoices'

    def get_queryset(self):
        return self.get_filtered_invoices(self.request)

    def post(self, request, *args, **kwargs):
        return self.get(request, *args, **kwargs)


class InvoicePrintView(InvoiceContextMixin, SalesRequiredMixin, DetailView):
    model = Invoice
    template_name = 'invoices/print.html'
    context_object_name = 'invoice'

    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)
        self.object.printed_count += 1
        self.object.save(update_fields=['printed_count'])
        return response


class GenerateInvoiceView(SalesRequiredMixin, View):
    def post(self, request, order_pk):
        order = get_object_or_404(Order, pk=order_pk)
        try:
            invoice = generate_invoice(order)
            messages.success(request, 'تم إصدار الفاتورة')
            return redirect('invoices:detail', pk=invoice.pk)
        except ValidationError as exc:
            messages.error(request, exc.message)
            return redirect('orders:detail', pk=order.pk)

# Create your views here.
