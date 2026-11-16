from django.urls import path

from .views import SettingsView
from .backup_views import BackupDownloadView, BackupPageView, BackupPreviewView


app_name = 'settings_app'

urlpatterns = [
    path('', SettingsView.as_view(), name='index'),
    path('backups/', BackupPageView.as_view(), name='backups'),
    path('backups/download/', BackupDownloadView.as_view(), name='backup_download'),
    path('backups/<uuid:job_id>/', BackupPreviewView.as_view(), name='backup_preview'),
]
