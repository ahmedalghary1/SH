from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import Branch, User


class BranchForm(forms.ModelForm):
    class Meta:
        model = Branch
        fields = ('name', 'code', 'phone', 'address', 'is_active')


class ArabicAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label='اسم المستخدم',
        widget=forms.TextInput(attrs={'placeholder': 'أدخل اسم المستخدم', 'autocomplete': 'username'}),
    )
    password = forms.CharField(
        label='كلمة المرور',
        widget=forms.PasswordInput(attrs={'placeholder': 'أدخل كلمة المرور', 'autocomplete': 'current-password'}),
    )

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.is_superuser and (not user.branch_id or not user.branch.is_active):
            raise forms.ValidationError('المعرض الخاص بهذا المستخدم غير نشط.', code='inactive_branch')


class UsernameWithSpacesMixin:
    def clean_username(self):
        username = (self.cleaned_data.get('username') or '').strip()
        if not username:
            raise forms.ValidationError('أدخل اسم المستخدم')
        return username


class UserCreateForm(UsernameWithSpacesMixin, UserCreationForm):
    password1 = forms.CharField(
        label='كلمة المرور',
        widget=forms.PasswordInput(attrs={'placeholder': 'كلمة مرور قوية', 'autocomplete': 'new-password'}),
    )
    password2 = forms.CharField(
        label='تأكيد كلمة المرور',
        widget=forms.PasswordInput(attrs={'placeholder': 'أعد كتابة كلمة المرور', 'autocomplete': 'new-password'}),
    )

    class Meta:
        model = User
        fields = ('username', 'email', 'phone', 'role', 'branch', 'is_active', 'password1', 'password2')
        labels = {
            'username': 'اسم المستخدم',
            'email': 'البريد الإلكتروني',
            'phone': 'الهاتف',
            'role': 'الدور',
            'is_active': 'نشط',
        }
        widgets = {
            'username': forms.TextInput(attrs={'placeholder': 'مثال: أحمد محمد'}),
            'email': forms.EmailInput(attrs={'placeholder': 'البريد الإلكتروني'}),
            'phone': forms.TextInput(attrs={'placeholder': 'رقم الهاتف'}),
        }


    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        self.fields['branch'].label = 'المعرض'
        self.fields['branch'].queryset = Branch.objects.filter(is_active=True).order_by('name')
        if actor and not actor.is_superuser:
            self.fields.pop('branch', None)

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.actor and not self.actor.is_superuser:
            user.branch = self.actor.branch
        if commit:
            user.save()
            self.save_m2m()
        return user


class UserUpdateForm(UsernameWithSpacesMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ('username', 'email', 'phone', 'role', 'branch', 'is_active')
        labels = {
            'username': 'اسم المستخدم',
            'email': 'البريد الإلكتروني',
            'phone': 'الهاتف',
            'role': 'الدور',
            'is_active': 'نشط',
        }
        widgets = {
            'username': forms.TextInput(attrs={'placeholder': 'اسم المستخدم'}),
            'email': forms.EmailInput(attrs={'placeholder': 'البريد الإلكتروني'}),
            'phone': forms.TextInput(attrs={'placeholder': 'رقم الهاتف'}),
        }

    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        self.fields['branch'].label = 'المعرض'
        self.fields['branch'].queryset = Branch.objects.filter(is_active=True).order_by('name')
        if actor and not actor.is_superuser:
            self.fields.pop('branch', None)

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.actor and not self.actor.is_superuser:
            user.branch = self.actor.branch
        if commit:
            user.save()
        return user
