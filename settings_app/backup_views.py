from django.contrib import messages
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import never_cache

from accounts.permissions import SuperuserRequiredMixin
from config.error_email import email_status
from .backup_errors import report_backup_error
from .backup_forms import BackupConfirmForm, BackupUploadForm
from .backup_services import BackupError, apply_import, build_backup, cleanup_archives, ensure_backup_schema, limits, stage_upload
from .models import BackupImport


@method_decorator(never_cache, name='dispatch')
class BackupAccessView(SuperuserRequiredMixin, View):
    pass


def page_context(form=None, backup_error='', error_reference=''):
    try:
        maximum = limits()['upload'] // (1024 * 1024)
    except BackupError as exc:
        maximum = None
        backup_error = backup_error or str(exc)
    return {
        'form': form if form is not None else BackupUploadForm(),
        'max_upload_mb': maximum,
        'backup_error': backup_error,
        'backup_ready': not backup_error,
        'error_reference': error_reference,
        'error_email': email_status(),
    }


def backup_failure_response(request, exc, operation):
    failure = report_backup_error(request, exc, operation)
    try:
        response = render(request, 'settings/backups.html',
                          page_context(backup_error=failure['message'], error_reference=failure['reference']),
                          status=failure['status'])
    except Exception:
        # A database failure can also break authenticated layout processors.
        from config.errors import _error
        response = _error(request, failure['status'], 'تعذر إكمال النسخ الاحتياطي', failure['message'])
    response['Cache-Control'] = 'private, no-store'
    response['X-Request-ID'] = failure['reference']
    return response


class BackupPageView(BackupAccessView):
    def get(self, request):
        try:
            ensure_backup_schema()
            cleanup_archives()
            limits()
            return render(request, 'settings/backups.html', page_context())
        except Exception as exc:
            return backup_failure_response(request, exc, 'open')

    def post(self, request):
        form = BackupUploadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                job = stage_upload(form.cleaned_data['archive'], request.user)
                return redirect('settings_app:backup_preview', job_id=job.pk)
            except BackupError as exc:
                form.add_error('archive', str(exc))
            except Exception as exc:
                return backup_failure_response(request, exc, 'preview')
        return render(request, 'settings/backups.html', page_context(form))


class BackupDownloadView(BackupAccessView):
    def get(self, request):
        try:
            stream = build_backup()
        except Exception as exc:
            return backup_failure_response(request, exc, 'download')
        filename = f'sh-backup-{timezone.localtime():%Y%m%d-%H%M%S}.zip'
        response = FileResponse(stream, as_attachment=True, filename=filename, content_type='application/zip')
        response['Cache-Control'] = 'private, no-store'
        response['X-Content-Type-Options'] = 'nosniff'
        return response


class BackupPreviewView(BackupAccessView):
    def get(self, request, job_id):
        job = get_object_or_404(BackupImport, pk=job_id, created_by=request.user)
        return render(request, 'settings/backup_preview.html', {
            'job': job, 'summary': job.summary, 'form': BackupConfirmForm(),
        })

    def post(self, request, job_id):
        job = get_object_or_404(BackupImport, pk=job_id, created_by=request.user)
        form = BackupConfirmForm(request.POST)
        if form.is_valid():
            try:
                result = apply_import(job.pk, request.user)
                messages.success(request, f'اكتمل الدمج: إضافة {result.summary["create"]} سجل، '
                                          f'وتحديث {result.summary["update"]} سجل دون مضاعفة الحركات.')
                return redirect('settings_app:backup_preview', job_id=result.pk)
            except BackupError as exc:
                form.add_error(None, str(exc))
            except Exception as exc:
                return backup_failure_response(request, exc, 'merge')
        return render(request, 'settings/backup_preview.html', {
            'job': job, 'summary': job.summary, 'form': form,
        })
