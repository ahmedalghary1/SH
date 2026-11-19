"""Replace the backed-up data in one transaction after writing a recovery ZIP."""
from collections import Counter, defaultdict
import logging
import os
from shutil import copyfileobj

from django.contrib.auth.hashers import identify_hasher, is_password_usable
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.models import Session
from django.db import connection, transaction
from django.db.models import F
from django.utils import timezone

from . import backup_services as backups
from .models import BackupBranchHistory, BackupIdentity, BackupImport


REPLACE = 'replace'
FRESH_IDS = {'accounts.user', 'accounts.branch'}
CONTENT_TYPE = 'contenttypes.contenttype'
logger = logging.getLogger('settings_app.backups')


def _has_admin(records):
    for row in records:
        if row['model'] != 'accounts.user':
            continue
        fields = row['fields']
        if fields['is_superuser'] is not True or fields['is_active'] is not True:
            continue
        password = fields['password']
        if not password or not is_password_usable(password):
            continue
        try:
            identify_hasher(password)
        except ValueError:
            continue
        return True
    return False


def _plan_replacement(manifest, records):
    if not _has_admin(records):
        raise backups.BackupError('تحتاج النسخة إلى حساب مسؤول أعلى نشط بكلمة مرور لاستخدامه بعد الاستعادة.')
    backups._validate_branch_links(records)
    source_keys, ids_by_model = {}, defaultdict(set)
    for record in records:
        label, raw = record['model'], record['source_pk']
        pk = int(raw) if len(raw) <= 19 else 0
        if not 0 < pk <= 9223372036854775807 or pk in ids_by_model[label]:
            raise backups.BackupError('تحتوي النسخة على أرقام سجلات مكررة أو خارج النطاق.')
        ids_by_model[label].add(pk)
        source_keys[record['uid']] = (label, pk)
    current, media = backups.collect_snapshot()
    media_plan = backups._plan_import_media(manifest, media)
    old_counts = Counter(row['model'] for row in current)
    new_counts = Counter(row['model'] for row in records)
    summary = {
        'mode': REPLACE,
        'created_at': manifest['created_at'],
        'branches': [{'code': branch['code'], 'name': branch['name']} for branch in manifest['branches']],
        'current_count': len(current),
        'restored_count': len(records),
        'media_count': len(media_plan),
        'missing_media': len(manifest.get('missing_media', [])),
        'rows': [{'label': backups.MODEL_LABELS.get(label, label), 'current': old_counts[label], 'incoming': new_counts[label]}
                 for label in sorted(old_counts.keys() | new_counts.keys())],
    }
    fingerprint = backups.digest({'data': current, 'media': sorted((name, item['sha256']) for name, item in media.items())})
    return {'fingerprint': fingerprint, 'summary': summary, 'mapped': source_keys, 'media': media_plan,
            'actions': dict.fromkeys(source_keys, 'create')}


def stage_replacement(upload, user):
    return backups._stage_upload(upload, user, _plan_replacement)


def _sequences(models):
    high_water, sequences = {}, {}
    with connection.cursor() as cursor:
        for label, model in models.items():
            table = model._meta.db_table
            if connection.vendor == 'postgresql':
                cursor.execute('SELECT pg_get_serial_sequence(%s, %s)', [table, model._meta.pk.column])
                sequence = cursor.fetchone()[0]
                if sequence is None:
                    continue
                cursor.execute('SELECT pg_sequence_last_value(%s::regclass)', [sequence])
                high_water[label] = cursor.fetchone()[0] or 0
                sequences[label] = sequence
            elif connection.vendor == 'sqlite' and label in FRESH_IDS | {CONTENT_TYPE}:
                cursor.execute('SELECT seq FROM sqlite_sequence WHERE name = %s', [table])
                row = cursor.fetchone()
                high_water[label] = row[0] if row else 0
    return high_water, sequences


def _allocate_identity_keys(records, mapped, current_max, high_water):
    # The PWA's queues and API sessions are keyed by user and branch ID.
    # Remap both above their previous sequences to isolate the restored data.
    labels = FRESH_IDS | {CONTENT_TYPE}
    next_ids = {label: max(current_max[label], high_water.get(label, 0)) + 1 for label in labels}
    content_types = {(app, name): pk for pk, app, name in
                     ContentType.objects.values_list('pk', 'app_label', 'model')}
    for record in records:
        label = record['model']
        if label not in labels:
            continue
        fields = record['fields']
        existing = content_types.get((fields['app_label'], fields['model'])) if label == CONTENT_TYPE else None
        if existing is None:
            existing = next_ids[label]
            next_ids[label] += 1
        mapped[record['uid']] = (label, existing)


def _clear_data(registry):
    # Django's foreign keys are deferred. Clear join tables and the entire
    # backed-up set together to allow cycles and bypass ordinary domain deletes.
    through = {field.remote_field.through for model in registry.values() for field in model._meta.many_to_many}
    models = through | set(registry.values()) | {BackupImport, BackupBranchHistory, BackupIdentity, Session}
    for model in sorted(models, key=lambda model: model._meta.db_table):
        model._base_manager.all()._raw_delete(connection.alias)


def _save_recovery_file(path):
    with backups.build_backup() as stream:
        destination = path.open('xb')
        try:
            with destination:
                copyfileobj(stream, destination)
                destination.flush()
                os.fsync(destination.fileno())
        except Exception:
            path.unlink(missing_ok=True)
            raise


def apply_replacement(job_id, user):
    created_paths = []
    recovery = None
    try:
        with backups.unscoped(), transaction.atomic():
            backups._lock_imports()
            jobs = BackupImport.objects.filter(pk=job_id, created_by=user)
            if connection.vendor == 'sqlite':
                # Obtain a writer lock before reading the preview and taking the safety backup.
                jobs.update(preview_digest=F('preview_digest'))
            job = jobs.select_for_update().first()
            if job is None or job.completed_at or job.summary.get('mode') != REPLACE:
                raise backups.BackupError('معاينة الاستعادة غير متاحة. ارفع النسخة من جديد.')
            backups._lock_tables()
            path, manifest, records = backups._read_staged_archive(job)
            plan = _plan_replacement(manifest, records)
            if plan['fingerprint'] != job.preview_digest:
                raise backups.BackupError('تغيرت البيانات أو الصور بعد المعاينة. ارفع النسخة مجددًا.')

            registry = backups.backup_models()
            high_water, sequences = _sequences(registry)
            current_max = {label: registry[label]._base_manager.order_by('-pk').values_list('pk', flat=True).first() or 0
                           for label in FRESH_IDS | {CONTENT_TYPE}}
            _allocate_identity_keys(records, plan['mapped'], current_max, high_water)
            staged_ids = list(BackupImport.objects.values_list('pk', flat=True))
            safety_path = backups.private_root() / f'pre-restore-{job.pk}.zip'
            _save_recovery_file(safety_path)
            recovery = safety_path

            _clear_data(registry)
            backups._apply_records(records, plan, replacing=True)
            connection.check_constraints(table_names=[model._meta.db_table for model in registry.values()])
            backups._install_media(path, plan, created_paths)
            BackupBranchHistory.objects.bulk_create([
                BackupBranchHistory(branch_id=plan['mapped'][branch['uid']][1],
                                    digest=branch['digest'], ancestors=branch['ancestors'])
                for branch in manifest['branches']
            ])
            if sequences:
                restored_max = defaultdict(int)
                for label, pk in plan['mapped'].values():
                    restored_max[label] = max(restored_max[label], pk)
                with connection.cursor() as cursor:
                    for label, sequence in sequences.items():
                        # setval survives rollback, so only advance sequences.
                        if restored_max[label] > high_water[label]:
                            cursor.execute('SELECT setval(%s::regclass, %s, true)', [sequence, restored_max[label]])
            transaction.on_commit(ContentType.objects.clear_cache, robust=True)
            for staged_id in staged_ids:
                transaction.on_commit(lambda job_id=staged_id: backups.discard_archive(job_id), robust=True)
    except Exception:
        for path in reversed(created_paths):
            path.unlink(missing_ok=True)
        if recovery is not None:
            recovery.unlink(missing_ok=True)
        raise
    logger.info('Full backup restored archive=%s actor=%s recovery=%s', manifest['archive_id'], user.pk, recovery.name)
    return {**plan['summary'], 'recovery_name': recovery.name, 'completed_at': timezone.now()}
