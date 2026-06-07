from django import forms

from finance.models import CashAccount
from orders.models import Order


class InvoiceFilterForm(forms.Form):
    q = forms.CharField(
        label='بحث',
        required=False,
        widget=forms.TextInput(attrs={'type': 'search', 'placeholder': 'رقم الفاتورة أو العميل أو الهاتف'}),
    )
    date_from = forms.DateField(label='من تاريخ', required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    date_to = forms.DateField(label='إلى تاريخ', required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    payment_method = forms.ChoiceField(
        label='طريقة الدفع',
        required=False,
        choices=(
            ('', 'كل طرق الدفع'),
            (Order.METHOD_CASH, 'نقدي'),
            (Order.METHOD_WALLET, 'محفظة'),
            (Order.METHOD_CREDIT, 'آجل'),
        ),
    )
    payment_status = forms.ChoiceField(
        label='حالة الدفع',
        required=False,
        choices=(('', 'كل حالات الدفع'),) + tuple(Order.PAYMENT_STATUS_CHOICES),
    )


class InvoicePaymentForm(forms.Form):
    cash_account = forms.ModelChoiceField(queryset=CashAccount.objects.filter(is_active=True), label='الخزنة')
    amount = forms.DecimalField(min_value=0.01, label='قيمة الدفعة')
    transaction_date = forms.DateField(label='تاريخ الدفعة', widget=forms.DateInput(attrs={'type': 'date'}))
    notes = forms.CharField(widget=forms.Textarea, required=False, label='ملاحظات')

    def __init__(self, *args, invoice=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.invoice = invoice
        if invoice:
            self.fields['amount'].widget.attrs.update({
                'max': str(invoice.order.remaining_amount),
                'step': '0.01',
                'placeholder': str(invoice.order.remaining_amount),
            })

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if self.invoice and amount > self.invoice.order.remaining_amount:
            raise forms.ValidationError('قيمة الدفعة أكبر من المتبقي على الفاتورة')
        return amount
