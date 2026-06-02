from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import DetailView, View

from accounts.permissions import SalesRequiredMixin
from orders.models import Order

from .models import Invoice
from .services import generate_invoice


class InvoiceDetailView(SalesRequiredMixin, DetailView):
    model = Invoice
    template_name = 'invoices/detail.html'
    context_object_name = 'invoice'


class InvoicePrintView(SalesRequiredMixin, DetailView):
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
