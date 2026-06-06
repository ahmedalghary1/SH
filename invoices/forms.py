from django import forms


class InvoiceFilterForm(forms.Form):
    q = forms.CharField(
        label='بحث',
        required=False,
        widget=forms.TextInput(attrs={'type': 'search', 'placeholder': 'رقم الفاتورة أو العميل أو الهاتف'}),
    )
    date_from = forms.DateField(label='من تاريخ', required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    date_to = forms.DateField(label='إلى تاريخ', required=False, widget=forms.DateInput(attrs={'type': 'date'}))
