from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404
from django.shortcuts import render


def _static_source_path(relative_path):
    candidate = Path(settings.STATIC_SOURCE_DIR) / relative_path
    if not candidate.is_file():
        raise Http404(f'{relative_path} not found')
    return candidate


def manifest_view(request):
    return FileResponse(
        _static_source_path('manifest.json').open('rb'),
        content_type='application/manifest+json',
    )


def service_worker_view(request):
    response = FileResponse(
        _static_source_path('service-worker.js').open('rb'),
        content_type='application/javascript',
    )
    response['Service-Worker-Allowed'] = '/'
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response


def offline_view(request):
    return render(request, 'offline.html')
