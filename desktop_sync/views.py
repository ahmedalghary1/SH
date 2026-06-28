from django.contrib import messages
from django.contrib.auth import get_user_model, login as django_login
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .models import DesktopSyncConfig, SyncOutbox
from .services import login_remote, pull_remote, push_pending, sync_once


def status_view(request):
    config = DesktopSyncConfig.load()
    return render(
        request,
        'desktop_sync/status.html',
        {
            'config': config,
            'pending_count': SyncOutbox.objects.filter(status=SyncOutbox.STATUS_PENDING).count(),
            'synced_count': SyncOutbox.objects.filter(status=SyncOutbox.STATUS_SYNCED).count(),
            'failed_count': SyncOutbox.objects.filter(status__in=[SyncOutbox.STATUS_FAILED, SyncOutbox.STATUS_CONFLICT]).count(),
            'recent_outbox': SyncOutbox.objects.order_by('-updated_at')[:20],
        },
    )


@require_POST
def login_view(request):
    username = request.POST.get('username', '').strip()
    password = request.POST.get('password', '')
    remote_api_url = request.POST.get('remote_api_url', '').strip()
    try:
        data = login_remote(username, password, remote_api_url)
        user_id = (data.get('user') or {}).get('id')
        user = get_user_model().objects.filter(pk=user_id).first()
        if user:
            django_login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        pull_remote()
        messages.success(request, 'تم الاتصال بالموقع وتحميل بيانات المستخدم والبضاعة بنجاح.')
    except Exception as exc:
        messages.error(request, f'تعذر تسجيل الدخول أو التحميل: {exc}')
    return redirect('desktop_sync:status')


@require_POST
def pull_view(request):
    try:
        pull_remote()
        messages.success(request, 'تم تحميل آخر البيانات من الموقع.')
    except Exception as exc:
        messages.error(request, f'فشل التحميل: {exc}')
    return redirect('desktop_sync:status')


@require_POST
def push_view(request):
    try:
        results = push_pending()
        messages.success(request, f'تم رفع {len(results)} عملية.')
    except Exception as exc:
        messages.error(request, f'فشل الرفع: {exc}')
    return redirect('desktop_sync:status')


@require_POST
def sync_view(request):
    try:
        sync_once()
        messages.success(request, 'تمت المزامنة بنجاح.')
    except Exception as exc:
        messages.error(request, f'فشلت المزامنة: {exc}')
    return redirect('desktop_sync:status')
