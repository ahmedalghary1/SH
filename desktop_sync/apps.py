from django.apps import AppConfig


class DesktopSyncConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'desktop_sync'

    def ready(self):
        from . import signals  # noqa: F401
