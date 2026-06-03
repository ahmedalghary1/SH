from django.contrib import messages
from django.urls import reverse_lazy
from django.views.generic import UpdateView

from accounts.permissions import ManagerRequiredMixin

from .forms import CompanySettingsForm
from .models import CompanySettings


class SettingsView(ManagerRequiredMixin, UpdateView):
    form_class = CompanySettingsForm
    template_name = 'settings/index.html'
    success_url = reverse_lazy('settings_app:index')

    def get_object(self, queryset=None):
        return CompanySettings.load()

    def form_valid(self, form):
        messages.success(self.request, 'تم حفظ إعدادات الشركة')
        return super().form_valid(form)
