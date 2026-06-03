from django import forms


class InvoiceFilterForm(forms.Form):
    date_from = forms.DateField(label='من تاريخ', required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    date_to = forms.DateField(label='إلى تاريخ', required=False, widget=forms.DateInput(attrs={'type': 'date'}))
