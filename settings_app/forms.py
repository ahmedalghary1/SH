from django import forms

from .models import CompanySettings


class CompanySettingsForm(forms.ModelForm):
    class Meta:
        model = CompanySettings
        fields = (
            'company_name', 'phone', 'email', 'address', 'tax_number', 'logo',
            'invoice_notes', 'thermal_paper_width', 'thermal_print_mode',
            'thermal_printer_name', 'max_sales_discount_percentage',
            'allow_manager_sell_below_cost',
        )
        labels = {
            'company_name': 'اسم الشركة',
            'phone': 'الهاتف',
            'email': 'البريد الإلكتروني',
            'address': 'العنوان',
            'tax_number': 'الرقم الضريبي',
            'logo': 'الشعار',
            'invoice_notes': 'ملاحظات الفاتورة',
            'thermal_paper_width': 'مقاس ورق طابعة الفواتير',
            'thermal_print_mode': 'طريقة طباعة الفواتير',
            'thermal_printer_name': 'اسم الطابعة الحرارية',
            'max_sales_discount_percentage': 'حد خصم المبيعات',
            'allow_manager_sell_below_cost': 'السماح للمدير بالبيع تحت التكلفة',
        }
        widgets = {
            'company_name': forms.TextInput(attrs={'placeholder': 'اسم الشركة'}),
            'phone': forms.TextInput(attrs={'placeholder': 'رقم الهاتف'}),
            'email': forms.EmailInput(attrs={'placeholder': 'البريد الإلكتروني'}),
            'address': forms.Textarea(attrs={'placeholder': 'عنوان الشركة'}),
            'tax_number': forms.TextInput(attrs={'placeholder': 'الرقم الضريبي'}),
            'invoice_notes': forms.Textarea(attrs={'placeholder': 'ملاحظات تظهر أسفل الفاتورة'}),
            'thermal_printer_name': forms.TextInput(attrs={'placeholder': 'اتركه فارغًا لاستخدام الطابعة الافتراضية'}),
        }
