from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import User


class ArabicAuthenticationForm(AuthenticationForm):
    username = forms.CharField(label='اسم المستخدم')
    password = forms.CharField(label='كلمة المرور', widget=forms.PasswordInput)


class UserCreateForm(UserCreationForm):
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
