import logging

from django.contrib import messages
from django.db import DatabaseError
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import never_cache

from accounts.permissions import SuperuserRequiredMixin
from .backup_forms import BackupConfirmForm, BackupUploadForm
from .backup_services import BackupError, apply_import, build_backup, cleanup_archives, ensure_backup_schema, limits, stage_upload
from .models import BackupImport


logger = logging.getLogger(__name__)


@method_decorator(never_cache, name='dispatch')
class BackupAccessView(SuperuserRequiredMixin, View):
    pass


def page_context(form=None, backup_error=''):
    return {
        'form': form if form is not None else BackupUploadForm(),
        'max_upload_mb': limits()['upload'] // (1024 * 1024),
        'backup_error': backup_error,
        'backup_ready': not backup_error,
    }


class BackupPageView(BackupAccessView):
    def get(self, request):
        backup_error = ''
        try:
            ensure_backup_schema()
            cleanup_archives()
        except BackupError as exc:
            backup_error = str(exc)
        except DatabaseError:
            logger.exception('Backup schema is unavailable')
            backup_error = 'تعذر قراءة بيانات النسخ الاحتياطي. تحقق من تحديث قاعدة البيانات واتصال الخادم.'
        except OSError:
            logger.exception('Could not remove an expired staged backup')
        return render(request, 'settings/backups.html', page_context(backup_error=backup_error))

    def post(self, request):
        form = BackupUploadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                job = stage_upload(form.cleaned_data['archive'], request.user)
                return redirect('settings_app:backup_preview', job_id=job.pk)
            except BackupError as exc:
                form.add_error('archive', str(exc))
            except (DatabaseError, OSError):
                logger.exception('Backup preview failed')
                form.add_error('archive', 'تعذر تجهيز المعاينة. تحقق من المساحة المتاحة ثم أعد المحاولة.')
        return render(request, 'settings/backups.html', page_context(form))


class BackupDownloadView(BackupAccessView):
    def get(self, request):
        try:
            stream = build_backup()
        except BackupError as exc:
            messages.error(request, str(exc))
            return redirect('settings_app:backups')
        except (DatabaseError, OSError):
            logger.exception('Full backup download failed')
            messages.error(request, 'تعذر تجهيز النسخة. تحقق من المساحة المتاحة وأعد المحاولة.')
            return redirect('settings_app:backups')
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
            except (DatabaseError, OSError):
                logger.exception('Backup merge failed: job=%s', job.pk)
                form.add_error(None, 'تعذر تطبيق الدمج؛ أُلغيت تغييرات هذه المحاولة. راجع الملف وأعد المعاينة.')
        return render(request, 'settings/backup_preview.html', {
            'job': job, 'summary': job.summary, 'form': form,
        })
