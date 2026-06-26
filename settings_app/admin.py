from django.contrib import admin

from .models import CompanySettings


@admin.register(CompanySettings)
class CompanySettingsAdmin(admin.ModelAdmin):
    list_display = ('company_name', 'phone', 'email', 'thermal_paper_width', 'thermal_print_mode', 'thermal_printer_name', 'updated_at')
