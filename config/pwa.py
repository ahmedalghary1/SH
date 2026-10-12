from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404
from django.shortcuts import render
from django.utils.cache import patch_cache_control, patch_vary_headers


def offline_scope(user, branch_id):
    if not user or not user.is_authenticated:
        return ''
    return f'u{user.pk}-b{branch_id or "all"}-r{user.role}-s{int(user.is_superuser)}'


class PwaScopeMiddleware:
    """Explicitly opt authenticated HTML into an identity-specific worker cache.

    HTTP caches must still revalidate private pages. The worker is the only
    component allowed to retain selected pages for offline use.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        branch = getattr(request, 'active_branch', None)
        branch_id = branch.pk if branch else None
        request.pwa_scope = offline_scope(user, branch_id)
        supplied_scope = request.headers.get('X-PWA-Scope')
        if supplied_scope and supplied_scope != request.pwa_scope:
            from django.http import JsonResponse
            return JsonResponse({'error': 'تغير الحساب أو المعرض. افتح الصفحة من جديد قبل المزامنة.', 'code': 'scope_changed'}, status=409)
        response = self.get_response(request)
        if request.pwa_scope:
            response['X-PWA-Scope'] = request.pwa_scope
            if request.method == 'GET' and 'text/html' in response.get('Content-Type', ''):
                patch_cache_control(response, private=True, no_cache=True)
                patch_vary_headers(response, ['Cookie'])
                if response.status_code == 200 and not request.path.startswith(('/accounts/', '/admin/', '/api/')):
                    response['X-PWA-Cacheable'] = '1'
        return response


def _static_source_path(relative_path):
    candidate = Path(settings.STATIC_SOURCE_DIR) / relative_path
    if not candidate.is_file():
        raise Http404(f'{relative_path} not found')
    return candidate


def manifest_view(request):
    response = FileResponse(
        _static_source_path('manifest.json').open('rb'),
        content_type='application/manifest+json',
    )
    response['Cache-Control'] = 'public, max-age=3600'
    return response


def service_worker_view(request):
    response = FileResponse(
        _static_source_path('service-worker.js').open('rb'),
        content_type='application/javascript',
    )
    response['Service-Worker-Allowed'] = '/'
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response


def offline_view(request):
    response = render(request, 'offline.html')
    response['Cache-Control'] = 'public, max-age=300'
    return response
