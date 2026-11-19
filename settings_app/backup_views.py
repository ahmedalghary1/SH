from django.contrib import messages
from django.contrib.auth import logout
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import never_cache

from accounts.permissions import SuperuserRequiredMixin
from config.error_email import email_status
from .backup_errors import report_backup_error
from .backup_forms import BackupConfirmForm, BackupReplaceConfirmForm, BackupResolutionForm, BackupUploadForm
from .backup_replace import REPLACE, apply_replacement, stage_replacement
from .backup_resolution import STRICT
from .backup_services import (
    BackupError, apply_import, build_backup, cleanup_archives, ensure_backup_schema, limits,
    preview_resolution,
)
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
                job = stage_replacement(form.cleaned_data['archive'], request.user)
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
    def render_preview(self, request, job, form=None, resolution_form=None):
        current = job.summary.get('resolution', STRICT)
        return render(request, 'settings/backup_preview.html', {
            'job': job, 'summary': job.summary,
            'form': form if form is not None else BackupConfirmForm(initial={'resolution': current}),
            'resolution_form': resolution_form if resolution_form is not None else BackupResolutionForm(
                initial={'resolution': current}),
            'can_apply': not job.summary['conflict_count'] or current != STRICT,
        })

    def get(self, request, job_id):
        job = get_object_or_404(BackupImport, pk=job_id, created_by=request.user)
        if job.summary.get('mode') == REPLACE:
            return self.render_replacement(request, job, BackupReplaceConfirmForm())
        return self.render_preview(request, job)

    def post(self, request, job_id):
        job = get_object_or_404(BackupImport, pk=job_id, created_by=request.user)
        if job.summary.get('mode') == REPLACE:
            form = BackupReplaceConfirmForm(request.POST)
            if form.is_valid():
                try:
                    result = apply_replacement(job.pk, request.user)
                except BackupError as exc:
                    form.add_error(None, str(exc))
                except Exception as exc:
                    return backup_failure_response(request, exc, 'restore')
                else:
                    logout(request)
                    return render(request, 'settings/backup_restored.html', {'summary': result})
            return self.render_replacement(request, job, form)
        if 'preview_resolution' in request.POST:
            resolution_form = BackupResolutionForm(request.POST)
            if resolution_form.is_valid():
                try:
                    preview_resolution(job.pk, request.user, resolution_form.cleaned_data['resolution'])
                    return redirect('settings_app:backup_preview', job_id=job.pk)
                except BackupError as exc:
                    resolution_form.add_error(None, str(exc))
                except Exception as exc:
                    return backup_failure_response(request, exc, 'preview')
            return self.render_preview(request, job, resolution_form=resolution_form)
        form = BackupConfirmForm(request.POST)
        if form.is_valid():
            try:
                result = apply_import(job.pk, request.user, resolution=form.cleaned_data['resolution'])
                summary = result.summary
                message = f'أضيف {summary["create"]} سجل وحُدّث {summary["update"]} سجل.'
                if summary.get('deferred_count'):
                    message += f' أُجّل {summary["deferred_count"]} سجل وفق المعاينة.'
                messages.success(request, message)
                return redirect('settings_app:backup_preview', job_id=result.pk)
            except BackupError as exc:
                form.add_error(None, str(exc))
            except Exception as exc:
                return backup_failure_response(request, exc, 'merge')
        return self.render_preview(request, job, form=form)

    def render_replacement(self, request, job, form):
        return render(request, 'settings/backup_replace_preview.html', {
            'job': job, 'summary': job.summary, 'form': form,
        })
