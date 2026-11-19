import sys

from django.contrib.admin import AdminSite, ModelAdmin
from django.contrib.admin.apps import AdminConfig


class SystemAdminConfig(AdminConfig):
    default_site = 'config.admin_site.SystemAdminSite'


class CompleteTablesMixin:
    list_per_page = sys.maxsize

    def get_paginator(self, request, queryset, per_page, *args, **kwargs):
        # Django passes its own fixed page size for object history.
        if request.resolver_match and request.resolver_match.url_name == f'{self.opts.app_label}_{self.opts.model_name}_history':
            per_page = self.list_per_page
        return super().get_paginator(request, queryset, per_page, *args, **kwargs)


class SystemAdminSite(AdminSite):
    def register(self, model_or_iterable, admin_class=None, **options):
        class TableAdmin(CompleteTablesMixin, admin_class or ModelAdmin):
            pass

        return super().register(model_or_iterable, TableAdmin, **options)
