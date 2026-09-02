from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Branch, User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('بيانات النظام', {'fields': ('role', 'phone')}),
    )
    fieldsets += (('Branch', {'fields': ('branch',)}),)
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('بيانات النظام', {'fields': ('role', 'phone')}),
    )
    add_fieldsets += (('Branch', {'fields': ('branch',)}),)
    list_display = ('username', 'email', 'role', 'branch', 'phone', 'is_active', 'is_staff')
    list_filter = ('branch', 'role', 'is_active', 'is_staff')
    search_fields = ('username', 'phone', 'email')

admin.site.register(Branch)
