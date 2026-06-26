import csv

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import F
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.generic import DetailView, ListView, View

from accounts.permissions import SalesRequiredMixin
from config.search import arabic_search_q
from finance.models import PaymentTransaction
from finance.services import collect_order_payment
from orders.models import Order
from settings_app.models import CompanySettings

from .forms import InvoiceFilterForm, InvoicePaymentForm
from .models import Invoice
from .pdf import build_invoice_report_pdf
from .services import generate_invoice


class InvoiceContextMixin:
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['company_settings'] = CompanySettings.load()
        invoice = getattr(self, 'object', None)
        if invoice:
            context['payment_rows'] = PaymentTransaction.objects.select_related(
                'cash_account', 'created_by',
            ).filter(
                related_order=invoice.order,
                transaction_type=PaymentTransaction.TYPE_CUSTOMER_PAYMENT,
                direction=PaymentTransaction.DIRECTION_IN,
            ).order_by('-transaction_date', '-created_at')
            context['payment_form'] = kwargs.get('payment_form') or InvoicePaymentForm(
                invoice=invoice,
                initial={'transaction_date': timezone.localdate()},
            )
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
            q = self.filter_form.cleaned_data.get('q')
            date_from = self.filter_form.cleaned_data.get('date_from')
            date_to = self.filter_form.cleaned_data.get('date_to')
            payment_method = self.filter_form.cleaned_data.get('payment_method')
            payment_status = self.filter_form.cleaned_data.get('payment_status')
            if q:
                qs = qs.filter(arabic_search_q(('invoice_number', 'order__order_number', 'order__customer__name', 'order__customer__phone'), q))
            if date_from:
                qs = qs.filter(issued_at__date__gte=date_from)
            if date_to:
                qs = qs.filter(issued_at__date__lte=date_to)
            if payment_method:
                qs = qs.filter(order__payment_method=payment_method)
            if payment_status:
                qs = qs.filter(order__payment_status=payment_status)
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
            q = form.cleaned_data.get('q')
            date_from = form.cleaned_data.get('date_from')
            date_to = form.cleaned_data.get('date_to')
            payment_method = form.cleaned_data.get('payment_method')
            payment_status = form.cleaned_data.get('payment_status')
            if q:
                qs = qs.filter(arabic_search_q(('invoice_number', 'order__order_number', 'order__customer__name', 'order__customer__phone'), q))
            if date_from:
                qs = qs.filter(issued_at__date__gte=date_from)
            if date_to:
                qs = qs.filter(issued_at__date__lte=date_to)
            if payment_method:
                qs = qs.filter(order__payment_method=payment_method)
            if payment_status:
                qs = qs.filter(order__payment_status=payment_status)
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
        writer.writerow(['رقم الفاتورة', 'رقم الطلب', 'العميل', 'المندوب', 'طريقة الدفع', 'حالة الدفع', 'الإجمالي', 'المدفوع', 'المتبقي', 'التاريخ'])
        for invoice in self.get_filtered_invoices(request):
            writer.writerow([
                invoice.invoice_number,
                invoice.order.order_number,
                invoice.order.customer or '',
                invoice.order.created_by or '',
                invoice.order.get_payment_method_display(),
                invoice.order.get_payment_status_display(),
                invoice.order.total,
                invoice.order.paid_amount,
                invoice.order.remaining_amount,
                invoice.issued_at,
            ])
        return response


class InvoicePDFExportView(InvoiceExportMixin, SalesRequiredMixin, View):
    def dispatch(self, request, *args, **kwargs):
        self.request = request
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        return self.build_response(request)

    def post(self, request):
        return self.build_response(request)

    def build_response(self, request):
        pdf_bytes = build_invoice_report_pdf(
            invoices=self.get_filtered_invoices(request),
            company_settings=CompanySettings.load(),
        )
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="invoice-report.pdf"'
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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company_settings = context['company_settings']
        paper_width = company_settings.thermal_paper_width or CompanySettings.THERMAL_WIDTH_80
        context['thermal_paper_width'] = int(paper_width)
        context['thermal_receipt_width'] = 52 if paper_width == CompanySettings.THERMAL_WIDTH_58 else 74
        context['thermal_print_mode'] = company_settings.thermal_print_mode or CompanySettings.PRINT_MODE_BROWSER
        context['thermal_printer_name'] = company_settings.thermal_printer_name or ''
        return context


class InvoicePrintMarkView(SalesRequiredMixin, View):
    def post(self, request, pk):
        qs = Invoice.objects.select_related('order__created_by')
        if request.user.role == 'sales' and not request.user.is_superuser:
            qs = qs.filter(order__created_by=request.user)
        invoice = get_object_or_404(qs, pk=pk)
        Invoice.objects.filter(pk=invoice.pk).update(printed_count=F('printed_count') + 1)
        return JsonResponse({'ok': True})


class InvoicePaymentCreateView(InvoiceContextMixin, SalesRequiredMixin, View):
    def get_invoice(self, request, pk):
        qs = Invoice.objects.select_related('order__customer', 'order__created_by')
        if request.user.role == 'sales' and not request.user.is_superuser:
            qs = qs.filter(order__created_by=request.user)
        return get_object_or_404(qs, pk=pk)

    def post(self, request, pk):
        invoice = self.get_invoice(request, pk)
        form = InvoicePaymentForm(request.POST, invoice=invoice)
        if form.is_valid():
            try:
                collect_order_payment(
                    order=invoice.order,
                    amount=form.cleaned_data['amount'],
                    cash_account=form.cleaned_data['cash_account'],
                    transaction_date=form.cleaned_data['transaction_date'],
                    notes=form.cleaned_data.get('notes') or f'دفعة من الفاتورة {invoice.invoice_number}',
                    user=request.user,
                )
                messages.success(request, 'تم تسجيل الدفعة وتحديث المتبقي')
                return redirect('invoices:detail', pk=invoice.pk)
            except ValidationError as exc:
                form.add_error(None, getattr(exc, 'message', str(exc)))
        view = InvoiceDetailView()
        view.request = request
        view.object = invoice
        return view.render_to_response(view.get_context_data(payment_form=form))


class GenerateInvoiceView(SalesRequiredMixin, View):
    def post(self, request, order_pk):
        order = get_object_or_404(Order, pk=order_pk)
        try:
            invoice = generate_invoice(order, user=request.user)
            messages.success(request, 'تم إصدار الفاتورة')
            return redirect('invoices:detail', pk=invoice.pk)
        except ValidationError as exc:
            messages.error(request, exc.message)
            return redirect('orders:detail', pk=order.pk)

# Create your views here.
