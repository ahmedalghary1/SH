"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
import shutil
import tempfile
import re
from pathlib import Path

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.staticfiles.views import serve as staticfiles_serve
from django.db import connection
from django.http import Http404, JsonResponse
from django.urls import include, path, re_path
from django.utils import timezone
from django.utils._os import safe_join
from django.views.static import serve as static_serve


def _check_database():
    """Test basic DB connectivity."""
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
        return 'ok', None
    except Exception as exc:
        return 'error', str(exc)


def _check_media_write():
    """Test write access to MEDIA_ROOT."""
    media_root = Path(settings.MEDIA_ROOT)
    try:
        media_root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=media_root, delete=True, prefix='healthcheck_') as tmp:
            tmp.write(b'ok')
        return 'ok', None
    except Exception as exc:
        return 'error', str(exc)


def _check_disk_space():
    """Check disk usage. Warn if > 90% used."""
    try:
        usage = shutil.disk_usage(settings.BASE_DIR)
        pct = usage.used / usage.total * 100
        status = 'ok' if pct < 90 else 'warning'
        detail = {
            'used_gb': round(usage.used / (1024 ** 3), 2),
            'free_gb': round(usage.free / (1024 ** 3), 2),
            'total_gb': round(usage.total / (1024 ** 3), 2),
            'used_pct': round(pct, 1),
        }
        return status, detail
    except Exception as exc:
        return 'error', str(exc)


def _check_migrations():
    """Check whether all migrations have been applied."""
    try:
        from django.db.migrations.executor import MigrationExecutor
        executor = MigrationExecutor(connection)
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if plan:
            return 'warning', f'{len(plan)} unapplied migration(s)'
        return 'ok', None
    except Exception as exc:
        return 'error', str(exc)


def health_check(request):
    """
    Comprehensive health check endpoint.

    In DEBUG mode: returns full details for each check.
    In production: returns a simple overall status (ok / degraded / error)
    to avoid leaking internal information.
    """
    checks = {
        'database': _check_database(),
        'media': _check_media_write(),
        'disk': _check_disk_space(),
        'migrations': _check_migrations(),
    }

    # Determine overall status
    statuses = [status for status, _ in checks.values()]
    if 'error' in statuses:
        overall = 'error'
    elif 'warning' in statuses:
        overall = 'degraded'
    else:
        overall = 'ok'

    http_status = 200 if overall != 'error' else 503

    if settings.DEBUG:
        # Full detail in development
        payload = {
            'status': overall,
            'timestamp': timezone.now().isoformat(),
            'checks': {
                name: {'status': status, 'detail': detail}
                for name, (status, detail) in checks.items()
            },
        }
    else:
        # Minimal response in production — no internal details exposed
        payload = {
            'status': overall,
            'timestamp': timezone.now().isoformat(),
        }

    return JsonResponse(payload, status=http_status)

def _prefix_pattern(url):
    return r'^%s(?P<path>.*)$' % re.escape(url.lstrip('/'))


def _media_roots():
    roots = [Path(settings.MEDIA_ROOT), *getattr(settings, 'MEDIA_FALLBACK_ROOTS', [])]
    unique_roots = []
    seen = set()
    for root in roots:
        root = Path(root).expanduser()
        marker = root.resolve()
        if marker in seen:
            continue
        seen.add(marker)
        unique_roots.append(root)
    return unique_roots


def serve_media_file(request, path):
    for media_root in _media_roots():
        try:
            candidate = Path(safe_join(media_root, path))
        except ValueError as exc:
            raise Http404('Media file not found') from exc
        if candidate.is_file():
            return static_serve(request, path=path, document_root=media_root)
    raise Http404('Media file not found')



static_urlpatterns = []
if settings.SERVE_STATIC_WITH_DJANGO:
    static_urlpatterns = [
        re_path(
            _prefix_pattern(settings.STATIC_URL),
            staticfiles_serve,
            {'insecure': True},
        ),
    ]
elif settings.DEBUG:
    static_urlpatterns = static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

media_urlpatterns = []
if settings.SERVE_MEDIA_WITH_DJANGO:
    media_urlpatterns = [
        re_path(
            _prefix_pattern(settings.MEDIA_URL),
            serve_media_file,
        ),
    ]

urlpatterns = static_urlpatterns + media_urlpatterns + [
    path('health/', health_check, name='health_check'),
    path('admin/', admin.site.urls),
    path('', include('dashboard.urls')),
    path('accounts/', include('accounts.urls')),
    path('products/', include('products.urls')),
    path('inventory/', include('inventory.urls')),
    path('customers/', include('customers.urls')),
    path('orders/', include('orders.urls')),
    path('invoices/', include('invoices.urls')),
    path('finance/', include('finance.urls')),
    path('purchases/', include('purchases.urls')),
    path('returns/', include('returns.urls')),
    path('reports/', include('reports.urls')),
    path('sales-reps/', include('sales_reps.urls')),
    path('settings/', include('settings_app.urls')),
    path('audit/', include('audit.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
