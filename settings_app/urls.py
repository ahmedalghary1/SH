from django.urls import path
from django.views.generic import TemplateView

from accounts.permissions import ManagerRequiredMixin


class SettingsView(ManagerRequiredMixin, TemplateView):
    template_name = 'settings/index.html'


app_name = 'settings_app'

urlpatterns = [
    path('', SettingsView.as_view(), name='index'),
]
