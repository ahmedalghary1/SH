from django import forms

from .models import CompanySettings


class CompanySettingsForm(forms.ModelForm):
    class Meta:
        model = CompanySettings
        fields = (
            'company_name', 'phone', 'email', 'address', 'tax_number', 'logo',
            'invoice_notes', 'max_sales_discount_percentage',
            'max_vip_discount_percentage', 'allow_manager_sell_below_cost',
        )
        labels = {
            'company_name': 'اسم الشركة',
            'phone': 'الهاتف',
            'email': 'البريد الإلكتروني',
            'address': 'العنوان',
            'tax_number': 'الرقم الضريبي',
            'logo': 'الشعار',
            'invoice_notes': 'ملاحظات الفاتورة',
            'max_sales_discount_percentage': 'حد خصم المبيعات',
            'max_vip_discount_percentage': 'حد خصم VIP',
            'allow_manager_sell_below_cost': 'السماح للمدير بالبيع تحت التكلفة',
        }
        widgets = {
            'company_name': forms.TextInput(attrs={'placeholder': 'اسم الشركة'}),
            'phone': forms.TextInput(attrs={'placeholder': 'رقم الهاتف'}),
            'email': forms.EmailInput(attrs={'placeholder': 'البريد الإلكتروني'}),
            'address': forms.Textarea(attrs={'placeholder': 'عنوان الشركة'}),
            'tax_number': forms.TextInput(attrs={'placeholder': 'الرقم الضريبي'}),
            'invoice_notes': forms.Textarea(attrs={'placeholder': 'ملاحظات تظهر أسفل الفاتورة'}),
        }
