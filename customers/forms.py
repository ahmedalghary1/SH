from django import forms

from .models import Customer, CustomerInteraction


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = (
            'name', 'customer_type', 'phone', 'whatsapp', 'email',
            'company_name', 'tax_number', 'address', 'credit_limit',
            'opening_balance', 'notes', 'is_active',
        )
        labels = {
            'name': 'اسم العميل',
            'customer_type': 'نوع العميل',
            'phone': 'الهاتف',
            'whatsapp': 'واتساب',
            'email': 'البريد الإلكتروني',
            'company_name': 'اسم الشركة',
            'tax_number': 'الرقم الضريبي',
            'address': 'العنوان',
            'credit_limit': 'حد الائتمان',
            'opening_balance': 'رصيد افتتاحي',
            'notes': 'ملاحظات',
            'is_active': 'نشط',
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'اسم العميل'}),
            'phone': forms.TextInput(attrs={'placeholder': 'رقم الهاتف الأساسي'}),
            'whatsapp': forms.TextInput(attrs={'placeholder': 'رقم واتساب إن وجد'}),
            'email': forms.EmailInput(attrs={'placeholder': 'البريد الإلكتروني'}),
            'company_name': forms.TextInput(attrs={'placeholder': 'اسم الشركة لعملاء الجملة'}),
            'tax_number': forms.TextInput(attrs={'placeholder': 'الرقم الضريبي إن وجد'}),
            'address': forms.Textarea(attrs={'placeholder': 'عنوان العميل أو الشركة'}),
            'notes': forms.Textarea(attrs={'placeholder': 'ملاحظات داخلية'}),
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('customer_type') in {Customer.TYPE_B2B, Customer.TYPE_WHOLESALE}:
            if not cleaned.get('company_name'):
                self.add_error('company_name', 'اسم الشركة مطلوب لعميل الجملة')
            if not cleaned.get('address'):
                self.add_error('address', 'عنوان الشركة مطلوب لعميل الجملة')
        return cleaned


class CustomerInteractionForm(forms.ModelForm):
    class Meta:
        model = CustomerInteraction
        fields = ('interaction_type', 'title', 'description', 'next_follow_up_date', 'is_completed')
        labels = {
            'interaction_type': 'نوع التفاعل',
            'title': 'العنوان',
            'description': 'الوصف',
            'next_follow_up_date': 'تاريخ المتابعة القادم',
            'is_completed': 'مكتمل',
        }
        widgets = {
            'next_follow_up_date': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.Textarea(attrs={'rows': 4}),
        }
