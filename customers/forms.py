from django import forms
from django.core import signing

from accounts.models import User

from .models import Customer, CustomerInteraction


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ('name', 'customer_type', 'phone', 'sales_representative', 'address', 'notes', 'credit_limit', 'opening_balance')
        labels = {
            'name': 'اسم العميل',
            'customer_type': 'نوع العميل',
            'phone': 'الهاتف',
            'sales_representative': 'مسؤول المبيعات',
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
        )
        self.fields['sales_representative'].required = False
        self.fields['phone'].required = False
        self.fields['sales_representative'].empty_label = 'بدون مسؤول محدد'
        self.fields['sales_representative'].queryset = User.objects.filter(
            role=User.ROLE_SALES,
            is_active=True,
        ).order_by('username')
        
        # Hide financial fields for non-manager users
        if user and not user.is_manager and not user.is_superuser:
            if 'sales_representative' in self.fields:
                del self.fields['sales_representative']
            if 'credit_limit' in self.fields:
                del self.fields['credit_limit']
            if 'opening_balance' in self.fields:
                del self.fields['opening_balance']


class SimpleCustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ('name', 'customer_type', 'phone', 'sales_representative', 'opening_balance', 'address', 'notes')
        labels = {
            'name': 'اسم العميل',
            'customer_type': 'نوع العميل',
            'phone': 'الهاتف',
            'sales_representative': 'مسؤول المبيعات',
            'opening_balance': 'الرصيد الافتتاحي',
            'address': 'العنوان',
            'notes': 'ملاحظات',
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'اسم العميل'}),
            'phone': forms.TextInput(attrs={'placeholder': 'رقم الهاتف'}),
            'opening_balance': forms.NumberInput(attrs={'placeholder': '0.00', 'step': '0.01'}),
            'address': forms.Textarea(attrs={'placeholder': 'عنوان العميل', 'rows': 3}),
            'notes': forms.Textarea(attrs={'placeholder': 'ملاحظات', 'rows': 3}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['customer_type'].choices = (
            (Customer.TYPE_RETAIL, 'قطاعي'),
            (Customer.TYPE_WHOLESALE, 'جملة'),
        )
        self.fields['sales_representative'].required = False
        self.fields['phone'].required = False
        self.fields['sales_representative'].empty_label = 'بدون مسؤول محدد'
        self.fields['sales_representative'].queryset = User.objects.filter(
            role=User.ROLE_SALES,
            is_active=True,
        ).order_by('username')
        if user and not user.is_manager and not user.is_superuser:
            del self.fields['sales_representative']


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
RETURN_REVIEW_SALT = 'customer-return-balance-review-v1'


class CustomerReturnReconciliationForm(forms.Form):
    review_token = forms.CharField(widget=forms.HiddenInput, max_length=200000)
    orders = forms.MultipleChoiceField(choices=(), label='الفواتير المراد تصحيحها',
                                       error_messages={'required': 'اختر فاتورة واحدة على الأقل',
                                                       'invalid_choice': 'إحدى الفواتير المحددة غير متاحة للتصحيح'})
    confirm = forms.BooleanField(label='راجعت الفواتير المحددة وأوافق على تصحيح المتبقي فيها',
                                 error_messages={'required': 'يجب تأكيد مراجعة الفواتير قبل التصحيح'})

    def __init__(self, *args, customer, user, report, **kwargs):
        super().__init__(*args, **kwargs)
        self.review = report
        self.token_error = None
        if self.is_bound:
            token = self.data.get('review_token', '')
            try:
                if not isinstance(token, str) or len(token) > 200000:
                    raise signing.BadSignature
                payload = signing.loads(token, salt=RETURN_REVIEW_SALT, max_age=1800)
                reviewed = payload['report']
                if (payload['actor_id'] != user.pk or reviewed['customer_id'] != customer.pk
                        or reviewed['branch_id'] != customer.branch_id):
                    raise signing.BadSignature
                self.review = reviewed
            except signing.SignatureExpired:
                self.token_error = 'انتهت صلاحية المراجعة. اضغط إعادة المراجعة ثم حدد الفواتير من جديد'
            except (signing.BadSignature, KeyError, TypeError, ValueError):
                self.token_error = 'تعذر التحقق من المراجعة. اضغط إعادة المراجعة قبل التصحيح'
        else:
            self.initial['review_token'] = signing.dumps(
                {'actor_id': user.pk, 'report': report}, salt=RETURN_REVIEW_SALT, compress=True,
            )
        self.fields['orders'].choices = [(str(row['order_id']), row['order_number']) for row in self.review['orders']
                                        if row['needs_repair'] and not row['problems']]

    def clean_review_token(self):
        if self.token_error:
            raise forms.ValidationError(self.token_error)
        return self.cleaned_data['review_token']
