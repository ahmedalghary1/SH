from django import forms

from .models import Customer, CustomerInteraction


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ('name', 'customer_type', 'phone', 'address', 'notes', 'credit_limit', 'opening_balance')
        labels = {
            'name': 'اسم العميل',
            'customer_type': 'نوع العميل',
            'phone': 'الهاتف',
            'address': 'العنوان',
            'notes': 'ملاحظات',
            'credit_limit': 'حد الائتمان',
            'opening_balance': 'الرصيد الافتتاحي',
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'اسم العميل'}),
            'phone': forms.TextInput(attrs={'placeholder': 'رقم الهاتف'}),
            'address': forms.Textarea(attrs={'placeholder': 'عنوان العميل', 'rows': 3}),
            'notes': forms.Textarea(attrs={'placeholder': 'ملاحظات', 'rows': 3}),
            'credit_limit': forms.NumberInput(attrs={'placeholder': '0.00', 'step': '0.01'}),
            'opening_balance': forms.NumberInput(attrs={'placeholder': '0.00', 'step': '0.01'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields['customer_type'].choices = (
            (Customer.TYPE_RETAIL, 'قطاعي'),
            (Customer.TYPE_WHOLESALE, 'جملة'),
            (Customer.TYPE_B2B, 'شركة'),
        )
        
        # Hide financial fields for non-manager users
        if user and not user.is_manager and not user.is_superuser:
            if 'credit_limit' in self.fields:
                del self.fields['credit_limit']
            if 'opening_balance' in self.fields:
                del self.fields['opening_balance']


class SimpleCustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ('name', 'customer_type', 'phone', 'opening_balance', 'address', 'notes')
        labels = {
            'name': 'اسم العميل',
            'customer_type': 'نوع العميل',
            'phone': 'الهاتف',
            'opening_balance': 'الرصيد الافتتاحي',
            'address': 'العنوان',
            'notes': 'ملاحظات',
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'اسم العميل'}),
            'phone': forms.TextInput(attrs={'placeholder': 'رقم الهاتف'}),
            'opening_balance': forms.NumberInput(attrs={'placeholder': '0.00', 'step': '0.01', 'min': '0'}),
            'address': forms.Textarea(attrs={'placeholder': 'عنوان العميل', 'rows': 3}),
            'notes': forms.Textarea(attrs={'placeholder': 'ملاحظات', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['customer_type'].choices = (
            (Customer.TYPE_RETAIL, 'قطاعي'),
            (Customer.TYPE_WHOLESALE, 'جملة'),
            (Customer.TYPE_B2B, 'شركة'),
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
