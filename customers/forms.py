from django import forms

from .models import Customer


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = (
            'name', 'customer_type', 'phone', 'whatsapp', 'email',
            'company_name', 'tax_number', 'address', 'notes', 'is_active',
        )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('customer_type') == Customer.TYPE_B2B:
            if not cleaned.get('company_name'):
                self.add_error('company_name', 'اسم الشركة مطلوب لعميل الجملة')
            if not cleaned.get('address'):
                self.add_error('address', 'عنوان الشركة مطلوب لعميل الجملة')
        return cleaned
