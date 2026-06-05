from django import forms

from .models import Customer, CustomerInteraction


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ('name', 'customer_type', 'phone', 'address')
        labels = {
            'name': 'اسم العميل',
            'customer_type': 'نوع العميل',
            'phone': 'الهاتف',
            'address': 'العنوان',
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'اسم العميل'}),
            'phone': forms.TextInput(attrs={'placeholder': 'رقم الهاتف'}),
            'address': forms.Textarea(attrs={'placeholder': 'عنوان العميل', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['customer_type'].choices = (
            (Customer.TYPE_RETAIL, 'قطاعي'),
            (Customer.TYPE_WHOLESALE, 'جملة'),
        )


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
