from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import User


class ArabicAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label='اسم المستخدم',
        widget=forms.TextInput(attrs={'placeholder': 'أدخل اسم المستخدم', 'autocomplete': 'username'}),
    )
    password = forms.CharField(
        label='كلمة المرور',
        widget=forms.PasswordInput(attrs={'placeholder': 'أدخل كلمة المرور', 'autocomplete': 'current-password'}),
    )


class UserCreateForm(UserCreationForm):
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
        fields = ('username', 'first_name', 'last_name', 'email', 'phone', 'role', 'is_active', 'password1', 'password2')
        labels = {
            'username': 'اسم المستخدم',
            'first_name': 'الاسم الأول',
            'last_name': 'اسم العائلة',
            'email': 'البريد الإلكتروني',
            'phone': 'الهاتف',
            'role': 'الدور',
            'is_active': 'نشط',
        }
        widgets = {
            'username': forms.TextInput(attrs={'placeholder': 'مثال: موظف_01'}),
            'first_name': forms.TextInput(attrs={'placeholder': 'الاسم الأول'}),
            'last_name': forms.TextInput(attrs={'placeholder': 'اسم العائلة'}),
            'email': forms.EmailInput(attrs={'placeholder': 'البريد الإلكتروني'}),
            'phone': forms.TextInput(attrs={'placeholder': 'رقم الهاتف'}),
        }


class UserUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'phone', 'role', 'is_active')
        labels = {
            'username': 'اسم المستخدم',
            'first_name': 'الاسم الأول',
            'last_name': 'اسم العائلة',
            'email': 'البريد الإلكتروني',
            'phone': 'الهاتف',
            'role': 'الدور',
            'is_active': 'نشط',
        }
        widgets = {
            'username': forms.TextInput(attrs={'placeholder': 'اسم المستخدم'}),
            'first_name': forms.TextInput(attrs={'placeholder': 'الاسم الأول'}),
            'last_name': forms.TextInput(attrs={'placeholder': 'اسم العائلة'}),
            'email': forms.EmailInput(attrs={'placeholder': 'البريد الإلكتروني'}),
            'phone': forms.TextInput(attrs={'placeholder': 'رقم الهاتف'}),
        }
