"""Portable, bounded ZIP backups and conservative transactional snapshot merges.

Primary keys are transport details. UUIDs identify business records across
databases. Balances are snapshots, never replayed transactions or added twice.
An overlapping branch can advance only from an unchanged known ancestor.
"""
from collections import Counter, defaultdict
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from functools import lru_cache
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import uuid
import zipfile

from django.apps import apps
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.core.management.color import no_style
from django.db import connection, models, transaction
from django.db.models import Max
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from config.branching import reset_current_branch, set_current_branch
from .models import BackupBranchHistory, BackupIdentity, BackupImport


FORMAT = 'sh-erp-complete-backup'
VERSION = 1
METADATA = {'settings_app.backupidentity', 'settings_app.backupbranchhistory', 'settings_app.backupimport'}
APPS = {'accounts', 'products', 'inventory', 'customers', 'orders', 'invoices',
        'finance', 'purchases', 'returns', 'sales_reps', 'settings_app', 'sync_api',
        'audit', 'auth', 'contenttypes', 'admin'}
HISTORY_ONLY = {'audit.auditlog', 'admin.logentry', 'sync_api.syncoperation', 'accounts.submissionreceipt'}
GLOBALS = {'accounts.branch', 'accounts.user', 'auth.group', 'auth.permission', 'contenttypes.contenttype'}
NAMESPACE = uuid.UUID('306dd37d-d987-4311-a447-0af38b6e8849')
MODEL_LABELS = {
    'accounts.branch': 'المعارض', 'accounts.user': 'المستخدمون',
    'accounts.submissionreceipt': 'إيصالات منع التكرار',
    'products.product': 'المنتجات', 'products.productvariant': 'ألوان ومقاسات المنتجات',
    'products.category': 'التصنيفات', 'products.color': 'الألوان', 'products.size': 'المقاسات',
    'inventory.warehouse': 'المخازن', 'inventory.stock': 'أرصدة المخزون',
    'inventory.stockbatch': 'دفعات المخزون', 'inventory.stockmovement': 'حركات المخزون',
    'customers.customer': 'العملاء', 'customers.customerinteraction': 'متابعات العملاء',
    'orders.order': 'فواتير وطلبات البيع', 'orders.orderitem': 'بنود البيع', 'invoices.invoice': 'الفواتير المطبوعة',
    'finance.cashaccount': 'الخزن والحسابات', 'finance.paymenttransaction': 'الحركات المالية',
    'purchases.supplier': 'الموردون', 'purchases.purchaseorder': 'طلبات الشراء',
    'purchases.purchaseorderitem': 'بنود الشراء', 'returns.salesreturn': 'مرتجعات البيع',
    'returns.salesreturnitem': 'بنود المرتجعات', 'returns.exchangeitem': 'بنود الاستبدال',
    'returns.returnaccountsettlement': 'تسويات المرتجعات',
    'sales_reps.salesrepstockassignment': 'عهد المندوبين',
    'sales_reps.salesrepcollection': 'تحصيلات المندوبين',
    'settings_app.companysettings': 'إعدادات الشركة', 'sync_api.syncoperation': 'سجل المزامنة',
    'audit.auditlog': 'سجل المراجعة', 'admin.logentry': 'سجل الإدارة',
    'auth.group': 'مجموعات المستخدمين', 'auth.permission': 'صلاحيات النظام',
    'contenttypes.contenttype': 'تعريفات ربط البيانات',
}


class BackupError(ValueError):
    pass


def ensure_backup_schema():
    executor = MigrationExecutor(connection)
    if executor.migration_plan(executor.loader.graph.leaf_nodes()):
        raise BackupError('تحديث قاعدة البيانات غير مكتمل. نفّذ python manage.py migrate على الخادم ثم أعد المحاولة.')


def limits():
    values = {
        'upload': getattr(settings, 'BACKUP_MAX_UPLOAD_BYTES', 512 * 1024 * 1024),
        'expanded': getattr(settings, 'BACKUP_MAX_EXPANDED_BYTES', 2 * 1024 * 1024 * 1024),
        'json': getattr(settings, 'BACKUP_MAX_JSON_BYTES', 100 * 1024 * 1024),
        'files': getattr(settings, 'BACKUP_MAX_FILES', 50000),
        'records': getattr(settings, 'BACKUP_MAX_RECORDS', 250000),
    }
    if any(not isinstance(value, int) or value <= 0 for value in values.values()):
        raise BackupError('حدود النسخ الاحتياطي في إعدادات الخادم يجب أن تكون أعدادًا موجبة.')
    return values


@contextmanager
def unscoped():
    token = set_current_branch(None)
    try:
        yield
    finally:
        reset_current_branch(token)


@lru_cache(maxsize=1)
def backup_models():
    return {m._meta.label_lower: m for m in apps.get_models()
            if m._meta.app_label in APPS and m._meta.managed and not m._meta.proxy
            and m._meta.label_lower not in METADATA}


def canonical(value):
    return json.dumps(value, cls=DjangoJSONEncoder, ensure_ascii=False,
                      sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def read_json(raw):
    def invalid_constant(value):
        raise ValueError(f'Non-finite JSON number: {value}')

    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result

    return json.loads(raw, parse_constant=invalid_constant, object_pairs_hook=unique_keys)


def safe_name(name):
    if (not isinstance(name, str) or not name or '\\' in name or ':' in name
            or any(ord(c) < 32 for c in name) or name.startswith('/')
            or any(p in {'', '.', '..'} or p.endswith((' ', '.')) for p in name.split('/'))):
        raise BackupError('تحتوي النسخة على مسار ملف غير مسموح.')
    if any(re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?', p, re.I)
           for p in name.split('/')):
        raise BackupError('اسم ملف داخل النسخة غير صالح.')
    return str(PurePosixPath(name))


def media_roots():
    roots = []
    for value in [settings.MEDIA_ROOT, *getattr(settings, 'MEDIA_FALLBACK_ROOTS', [])]:
        root = Path(value).resolve()
        if root not in roots:
            roots.append(root)
    return roots


def media_inventory():
    found = {}
    for root in media_roots():
        if not root.is_dir():
            continue
        for path in sorted(root.rglob('*')):
            # Never follow an uploaded symlink outside the media tree.
            if path.is_symlink():
                raise BackupError('يوجد رابط رمزي في مجلد المرفقات؛ يلزم مراجعته قبل النسخ.')
            if path.is_file():
                relative = safe_name(path.relative_to(root).as_posix())
                if not path.resolve().is_relative_to(root):
                    raise BackupError('مسار مرفق خارج مجلد الصور.')
                if relative not in found:
                    found[relative] = {'path': relative, 'size': path.stat().st_size,
                                       'sha256': file_digest(path), 'source': path}
    return found


@lru_cache(maxsize=1)
def schema():
    return {label: {
        'fields': {f.name: [f.get_internal_type(), f.null, f.max_length,
                            getattr(f, 'max_digits', None), getattr(f, 'decimal_places', None),
                            f.remote_field.model._meta.label_lower if f.is_relation else None]
                   for f in model._meta.concrete_fields if not f.primary_key},
        'm2m': {f.name: f.remote_field.model._meta.label_lower for f in model._meta.many_to_many},
    } for label, model in backup_models().items()}


def _global_uid(obj):
    label = obj._meta.label_lower
    keys = {
        'accounts.branch': lambda: obj.code,
        'accounts.user': lambda: obj.username,
        'auth.group': lambda: obj.name,
        'contenttypes.contenttype': lambda: f'{obj.app_label}/{obj.model}',
        'auth.permission': lambda: f'{obj.content_type.app_label}/{obj.content_type.model}/{obj.codename}',
    }
    return uuid.uuid5(NAMESPACE, f'{label}:{keys[label]()}') if label in keys else uuid.uuid4()


def collect_snapshot(preferred=None):
    """Called inside a transaction; only UUID bookkeeping may be created."""
    preferred = {(label, str(pk)): uid for (label, pk), uid in (preferred or {}).items()}
    identity_rows = list(BackupIdentity.objects.order_by('-is_primary', 'id'))
    identities = {}
    used_uids = {str(item.uid) for item in identity_rows}
    for item in identity_rows:
        identities.setdefault((item.model_label, item.object_pk), str(item.uid))
    objects = {}
    additions = []
    for label, model in backup_models().items():
        for obj in model._base_manager.order_by('pk').iterator():
            key = (label, str(obj.pk))
            objects[key] = obj
            if key not in identities:
                uid = _global_uid(obj)
                if str(uid) in used_uids:
                    uid = uuid.uuid4()
                used_uids.add(str(uid))
                additions.append(BackupIdentity(uid=uid, model_label=label, object_pk=str(obj.pk), is_primary=True))
                identities[key] = str(uid)
    if additions:
        BackupIdentity.objects.bulk_create(additions)
    identities.update(preferred)
    media = media_inventory()
    records = []
    for key, obj in objects.items():
        fields = {}
        for field in obj._meta.concrete_fields:
            if field.primary_key:
                continue
            value = field.value_from_object(obj)
            if field.is_relation:
                related_key = (field.remote_field.model._meta.label_lower, str(value))
                if value is not None and related_key not in identities:
                    raise BackupError(f'يوجد رابط مفقود في بيانات {obj._meta.verbose_name}.')
                value = identities[related_key] if value is not None else None
            elif isinstance(field, models.FileField):
                name = str(value or '')
                if name:
                    safe_name(name)
                value = {'path': name, 'sha256': media.get(name, {}).get('sha256')}
            fields[field.name] = value
        many = {}
        for field in obj._meta.many_to_many:
            label = field.remote_field.model._meta.label_lower
            many[field.name] = sorted(identities[(label, str(pk))]
                                      for pk in getattr(obj, field.name).values_list('pk', flat=True))
        record = {'uid': identities[key], 'model': key[0], 'source_pk': key[1],
                  'fields': fields, 'm2m': many}
        records.append(record)
    # Convert dates, decimals and UUIDs to the exact portable JSON representation.
    records = json.loads(canonical(records))
    _encode_internal_references(records)
    return records, media


def _encode_internal_references(records):
    by_key = {(r['model'], r['source_pk']): r['uid'] for r in records}
    by_uid = {r['uid']: r for r in records}
    names = {m.__name__: label for label, m in backup_models().items()}
    for record in records:
        fields, extras = record['fields'], {}
        if record['model'] in {'audit.auditlog', 'admin.logentry'}:
            label = names.get(fields.get('model_name'))
            if record['model'] == 'admin.logentry':
                ct = by_uid.get(fields['content_type'])
                label = f"{ct['fields']['app_label']}.{ct['fields']['model']}" if ct else None
            ref = by_key.get((label, str(fields.get('object_id'))))
            if ref:
                extras['object_id'] = ref
        if record['model'] == 'finance.paymenttransaction':
            match = re.fullmatch(r'PUR-RET-(\d+)', fields.get('reference') or '')
            ref = by_key.get(('inventory.stockmovement', match[1])) if match else None
            if ref:
                extras['purchase_return_movement'] = ref
        if record['model'] == 'sync_api.syncoperation':
            label = names.get(fields.get('server_model'))
            ref = by_key.get((label, str(fields.get('server_object_id'))))
            if ref:
                extras['server_object_id'] = ref
            response = fields.get('response_json') or {}
            if isinstance(response, dict):
                response_refs = {}
                for field_name, target in {'server_id': label, 'variant_id': 'products.productvariant',
                                           'product_id': 'products.product', 'order_id': 'orders.order',
                                           'invoice_id': 'invoices.invoice'}.items():
                    ref = by_key.get((target, str(response.get(field_name))))
                    if ref:
                        response_refs[field_name] = ref
                if response_refs:
                    extras['response_refs'] = response_refs
        if extras:
            record['refs'] = extras


def record_value(record):
    fields = deepcopy(record['fields'])
    model = backup_models()[record['model']]
    for field in model._meta.concrete_fields:
        if field.name == 'updated_at' or (record['model'] == 'accounts.user' and field.name == 'last_login'):
            fields.pop(field.name, None)
        if isinstance(field, models.FileField):
            value = fields[field.name]
            fields[field.name] = value.get('sha256') or value.get('path') or ''
    # Primary keys embedded in these two columns are represented by portable refs.
    for name, ref in record.get('refs', {}).items():
        if name in {'object_id', 'server_object_id'}:
            fields[name] = ref
        elif name == 'response_refs':
            fields['response_json'] = {**fields['response_json'], **ref}
        elif name == 'purchase_return_movement':
            fields['reference'] = f'PUR-RET-{ref}'
    return {'uid': record['uid'], 'model': record['model'], 'fields': fields, 'm2m': record['m2m']}


def snapshot_digest(records):
    return digest(sorted((record_value(r) for r in records if r['model'] not in HISTORY_ONLY),
                         key=lambda r: r['uid']))


def branch_digest(records, branch_uid):
    business = [record_value(r) for r in records
                if r['model'] not in HISTORY_ONLY | GLOBALS and r['fields'].get('branch') == branch_uid]
    return digest(sorted(business, key=lambda r: r['uid']))


def _remember_branch(branch_pk, current):
    history = BackupBranchHistory.objects.filter(branch_id=branch_pk).first()
    ancestors = list(history.ancestors) if history else []
    if history and history.digest != current and history.digest not in ancestors:
        ancestors.append(history.digest)
    BackupBranchHistory.objects.update_or_create(branch_id=branch_pk,
                                                 defaults={'digest': current, 'ancestors': ancestors})
    return ancestors


def build_backup():
    """Return a rewound temporary ZIP stream; caller owns closing it."""
    ensure_backup_schema()
    temporary = tempfile.TemporaryFile()
    nested = connection.in_atomic_block
    try:
        with unscoped(), transaction.atomic():
            if connection.vendor == 'postgresql' and not nested:
                with connection.cursor() as cursor:
                    cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            records, media = collect_snapshot()
            if len(records) > limits()['records'] or len(media) + 2 > limits()['files']:
                raise BackupError('البيانات تتجاوز حدود النسخ الحالية؛ عدّل حدود النسخ في إعدادات الخادم.')
            branches = []
            for record in records:
                if record['model'] == 'accounts.branch':
                    current = branch_digest(records, record['uid'])
                    branches.append({'uid': record['uid'], 'code': record['fields']['code'],
                                     'name': record['fields']['name'], 'digest': current,
                                     'ancestors': _remember_branch(record['source_pk'], current)})
            payload = canonical(records)
            manifest = {
                'format': FORMAT, 'version': VERSION, 'archive_id': str(uuid.uuid4()),
                'created_at': timezone.now().isoformat(), 'schema': schema(), 'branches': branches,
                'data_sha256': hashlib.sha256(payload).hexdigest(),
                'counts': dict(Counter(r['model'] for r in records)),
                'media': [{k: v for k, v in item.items() if k != 'source'} for item in media.values()],
                'missing_media': sorted({v['path'] for r in records for v in r['fields'].values()
                                         if isinstance(v, dict) and 'path' in v and v['path'] and not v['sha256']}),
            }
            if len(payload) > limits()['json']:
                raise BackupError('حجم بيانات النسخة يتجاوز الحد المسموح على الخادم.')
            if len(payload) + sum(m['size'] for m in media.values()) > limits()['expanded']:
                raise BackupError('حجم الصور والبيانات يتجاوز حدود النسخ الحالية.')
            with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
                archive.writestr('manifest.json', canonical(manifest))
                archive.writestr('data.json', payload)
                for item in media.values():
                    archive.write(item['source'], f"media/{item['path']}")
                    if file_digest(item['source']) != item['sha256']:
                        raise BackupError('تغيرت صورة أثناء تجهيز النسخة؛ أعد التنزيل.')
            if temporary.tell() > limits()['upload']:
                raise BackupError('حجم النسخة يتجاوز حد الرفع الحالي؛ عدّل حدود النسخ قبل تنزيلها.')
        temporary.seek(0)
        return temporary
    except Exception:
        temporary.close()
        raise


def read_archive(path):
    """Validate the complete archive without extracting it into a served path."""
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            names = set()
            if len(entries) > limits()['files'] or sum(e.file_size for e in entries) > limits()['expanded']:
                raise BackupError('النسخة تتجاوز الحد المسموح للملفات أو الحجم بعد فك الضغط.')
            for entry in entries:
                name = safe_name(entry.filename)
                if name in names or entry.is_dir() or stat.S_ISLNK(entry.external_attr >> 16) or entry.flag_bits & 1:
                    raise BackupError('بنية ZIP غير مسموحة: ملف مكرر أو رابط أو تشفير غير مدعوم.')
                names.add(name)
            for name in ['manifest.json', 'data.json']:
                if name not in names or archive.getinfo(name).file_size > limits()['json']:
                    raise BackupError('النسخة لا تحتوي ملفات تعريف وبيانات صالحة.')
            manifest = read_json(archive.read('manifest.json'))
            raw = archive.read('data.json')
            if not isinstance(manifest, dict) or manifest.get('format') != FORMAT or manifest.get('version') != VERSION:
                raise BackupError('ارفع ملف ZIP كاملًا تم تنزيله من أداة النسخ بهذا النظام.')
            if manifest.get('schema') != schema():
                raise BackupError('بنية النسخة لا توافق إصدار النظام؛ حدّث النسخة والخادم إلى إصدار متوافق.')
            uuid.UUID(manifest['archive_id'])
            if hashlib.sha256(raw).hexdigest() != manifest.get('data_sha256'):
                raise BackupError('بيانات النسخة تالفة أو تغيرت بعد إنشائها.')
            records = read_json(raw)
            _validate_records(records, manifest)
            expected = {'manifest.json', 'data.json'}
            media_names = set()
            for item in manifest['media']:
                name = safe_name(item['path'])
                if name in media_names or not isinstance(item['size'], int) or item['size'] < 0:
                    raise BackupError('تعريف المرفقات غير صالح.')
                media_names.add(name)
                zipped = f'media/{name}'
                expected.add(zipped)
                if zipped not in names or archive.getinfo(zipped).file_size != item['size']:
                    raise BackupError('يوجد ملف مرفق مفقود أو ناقص داخل النسخة.')
                result = hashlib.sha256()
                with archive.open(zipped) as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        result.update(chunk)
                if result.hexdigest() != item['sha256']:
                    raise BackupError('إحدى الصور أو المرفقات تالفة داخل النسخة.')
            if expected != names:
                raise BackupError('تحتوي النسخة ملفات غير معرفة في فهرسها.')
            indexed_media = {m['path']: m['sha256'] for m in manifest['media']}
            for r in records:
                for f in backup_models()[r['model']]._meta.concrete_fields:
                    if isinstance(f, models.FileField):
                        value = r['fields'][f.name]
                        if value['sha256'] and indexed_media.get(value['path']) != value['sha256']:
                            raise BackupError('رابط الصورة لا يوافق فهرس المرفقات.')
            return manifest, records
    except BackupError:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError, zipfile.BadZipFile, NotImplementedError) as exc:
        raise BackupError('تعذر قراءة النسخة. تأكد من سلامة ملف ZIP واكتمال تنزيله.') from exc


def _validate_records(records, manifest):
    if not isinstance(records, list) or len(records) > limits()['records']:
        raise BackupError('عدد سجلات النسخة غير صالح.')
    known, source_keys = {}, set()
    registry = backup_models()
    definitions = schema()
    for record in records:
        if not isinstance(record, dict) or record.get('model') not in registry:
            raise BackupError('يوجد نوع بيانات غير مدعوم في النسخة.')
        uid = str(uuid.UUID(record['uid']))
        key = (record['model'], record['source_pk'])
        if (uid != record['uid'] or uid in known or key in source_keys
                or not isinstance(key[1], str) or not key[1].isascii() or not key[1].isdigit()):
            raise BackupError('معرفات السجلات مكررة أو غير صالحة.')
        known[uid] = record
        source_keys.add(key)
        definition = definitions[record['model']]
        if set(record['fields']) != set(definition['fields']) or set(record['m2m']) != set(definition['m2m']):
            raise BackupError('حقول النسخة ناقصة أو غير متوافقة.')
        for field in registry[record['model']]._meta.concrete_fields:
            if field.primary_key:
                continue
            value = record['fields'][field.name]
            if field.is_relation:
                if value is None and not field.null:
                    raise BackupError('يوجد رابط إلزامي مفقود في النسخة.')
            elif isinstance(field, models.FileField):
                if (not isinstance(value, dict) or set(value) != {'path', 'sha256'}
                        or not isinstance(value['path'], str)
                        or (value['sha256'] is not None and not re.fullmatch('[0-9a-f]{64}', str(value['sha256'])))):
                    raise BackupError('بيانات صورة غير صالحة.')
                if value['path']:
                    safe_name(value['path'])
            else:
                try:
                    parsed = field.to_python(value)
                    if parsed is None and not field.null:
                        raise ValueError('null')
                    # Database constraints remain authoritative for legacy data.
                    if isinstance(parsed, str) and field.max_length and len(parsed) > field.max_length:
                        raise ValueError('length')
                except (ValueError, TypeError, ValidationError) as exc:
                    raise BackupError(f'قيمة غير صالحة في {record["model"]}.{field.name}.') from exc
    for record in records:
        for field in registry[record['model']]._meta.concrete_fields:
            if field.is_relation:
                value = record['fields'][field.name]
                if value is not None and (value not in known or known[value]['model'] != field.remote_field.model._meta.label_lower):
                    raise BackupError('رابط داخل النسخة يشير إلى سجل مفقود أو من نوع مختلف.')
        for name, values in record['m2m'].items():
            field = registry[record['model']]._meta.get_field(name)
            if not isinstance(values, list) or len(values) != len(set(values)) or any(
                v not in known or known[v]['model'] != field.remote_field.model._meta.label_lower for v in values
            ):
                raise BackupError('علاقة متعددة غير صالحة داخل النسخة.')
        for ref in record.get('refs', {}).values():
            values = ref.values() if isinstance(ref, dict) else [ref]
            if any(v not in known for v in values):
                raise BackupError('مرجع تاريخي غير صالح داخل النسخة.')
    branch_records = {r['uid']: r for r in records if r['model'] == 'accounts.branch'}
    if not isinstance(manifest.get('branches'), list) or len(manifest['branches']) != len(branch_records):
        raise BackupError('فهرس المعارض غير كامل.')
    seen = set()
    for branch in manifest['branches']:
        uid = branch['uid']
        if uid not in branch_records or uid in seen or branch['digest'] != branch_digest(records, uid):
            raise BackupError('بصمة بيانات المعرض غير صحيحة.')
        seen.add(uid)
        if not isinstance(branch.get('ancestors'), list) or any(not re.fullmatch('[0-9a-f]{64}', h) for h in branch['ancestors']):
            raise BackupError('تاريخ النسخة غير صالح.')
    if not isinstance(manifest.get('media'), list):
        raise BackupError('فهرس الصور غير صالح.')


def _natural_keys(model):
    keys = [(f.name,) for f in model._meta.concrete_fields if f.unique and not f.primary_key]
    keys += list(model._meta.unique_together)
    keys += [c.fields for c in model._meta.constraints
             if isinstance(c, models.UniqueConstraint) and c.fields and c.condition is None]
    if model._meta.label_lower == 'settings_app.companysettings':
        keys.append(('branch',))
    return keys


def _map_existing(records):
    registry = backup_models()
    mapped, existing = {}, {}
    for offset in range(0, len(records), 500):
        for identity in BackupIdentity.objects.filter(uid__in=[r['uid'] for r in records[offset:offset + 500]]):
            model = registry.get(identity.model_label)
            if model and model._base_manager.filter(pk=identity.object_pk).exists():
                mapped[str(identity.uid)] = (identity.model_label, int(identity.object_pk))
    pending = list(records)
    while pending:
        progress, remaining = False, []
        for record in pending:
            uid, label = record['uid'], record['model']
            if uid in mapped:
                if mapped[uid][0] != label:
                    raise BackupError('معرف ثابت مستخدم لنوع مختلف من البيانات.')
                continue
            model, matches = registry[label], set()
            keys = _natural_keys(model)
            if (label == 'finance.cashaccount' and record['fields']['account_type'] == 'sales_rep_cash'
                    and record['fields']['assigned_user'] is not None):
                keys.append(('branch', 'assigned_user', 'account_type'))
            for key in keys:
                lookup = {}
                for name in key:
                    field = model._meta.get_field(name)
                    value = record['fields'][name]
                    if value is None:
                        break
                    if field.is_relation:
                        if value not in mapped:
                            break
                        value = mapped[value][1]
                    lookup[field.attname] = value
                else:
                    matches.update(model._base_manager.filter(**lookup).values_list('pk', flat=True)[:2])
            if len(matches) > 1:
                raise BackupError('تعارض في الأكواد أو الروابط؛ أكثر من سجل حالي يطابق سجلًا في النسخة.')
            if matches:
                mapped[uid] = (label, matches.pop())
                progress = True
            else:
                remaining.append(record)
        if not progress:
            break
        pending = remaining
    used = set()
    for uid, key in mapped.items():
        if key in used:
            raise BackupError('تحتوي النسخة سجلين يطابقان السجل الحالي نفسه؛ لم يتم دمجهما تلقائيًا.')
        used.add(key)
        existing[uid] = key
    # Allocate new local keys without trusting source primary keys. The apply
    # path locks the tables and rechecks the preview before using these keys.
    next_ids = {label: (model._base_manager.aggregate(value=Max('pk'))['value'] or 0) + 1
                for label, model in registry.items()}
    for record in records:
        if record['uid'] not in mapped:
            label = record['model']
            mapped[record['uid']] = (label, next_ids[label])
            next_ids[label] += 1
    return mapped, existing


def _media_plan(manifest, local_media):
    result = {}
    used = {name.casefold(): (name, item['sha256']) for name, item in local_media.items()}

    def collides(name):
        key = name.casefold()
        parts = key.split('/')
        return (any('/'.join(parts[:i]) in used for i in range(1, len(parts)))
                or any(other.startswith(key + '/') for other in used))

    for item in manifest['media']:
        name = item['path']
        prior = used.get(name.casefold())
        same = prior is not None and prior[1] == item['sha256']
        target = prior[0] if same else name
        if (prior is not None and not same) or collides(target):
            suffix = PurePosixPath(name).suffix.lower()
            suffix = suffix if re.fullmatch(r'\.[a-z0-9]{1,10}', suffix) else ''
            target = f"restored/{item['sha256'][:2]}/{item['sha256']}{suffix}"
            if collides(target):
                target = f"restored-{item['sha256']}{suffix}"
            if target.casefold() in used and used[target.casefold()][1] != item['sha256']:
                raise BackupError('يوجد تعارض غير متوقع في مسار صورة مستعادة.')
            if collides(target):
                raise BackupError('يوجد تعارض في مسار المرفقات؛ لم يطبق الدمج.')
        reused = same or (target.casefold() in used and used[target.casefold()][1] == item['sha256'])
        result[name] = {**item, 'target': target, 'reused': reused}
        used[target.casefold()] = (target, item['sha256'])
    return result


def plan_merge(manifest, records):
    with unscoped():
        mapped, existing = _map_existing(records)
        preferred = {key: uid for uid, key in existing.items()}
        current, media = collect_snapshot(preferred)
        current_by_uid = {r['uid']: r for r in current}
        incoming_by_uid = {r['uid']: r for r in records}
        actions, conflicts, retained = {}, [], 0
        advance, preserve = set(), set()
        for branch in manifest['branches']:
            uid = branch['uid']
            source_business = {r['uid'] for r in records if r['model'] not in HISTORY_ONLY | GLOBALS
                               and r['fields'].get('branch') == uid}
            local_business = {r['uid'] for r in current if r['model'] not in HISTORY_ONLY | GLOBALS
                              and r['fields'].get('branch') == uid}
            local_digest = branch_digest(current, uid)
            history = BackupBranchHistory.objects.filter(branch_id=mapped[uid][1]).first() if uid in existing else None
            known_past = {history.digest, *history.ancestors} if history else set()
            # No deletion is performed by a merge. If a descendant snapshot
            # removed records, changing balances while retaining those records
            # would be unsafe, so that case remains a visible conflict.
            if local_digest in branch['ancestors'] and not (local_business - source_business):
                advance.add(uid)
            elif branch['digest'] in known_past and not (source_business - local_business):
                preserve.add(uid)
        for record in records:
            uid, label, fields = record['uid'], record['model'], record['fields']
            local = current_by_uid.get(uid)
            if uid not in existing:
                actions[uid] = 'create'
            elif label in GLOBALS:
                actions[uid] = 'skip'
                if label == 'accounts.user':
                    # Never move an existing login to another branch or replace
                    # its password, privileges or group memberships.
                    if fields['branch'] != local['fields']['branch']:
                        conflicts.append({'model': label, 'label': 'حساب مستخدم', 'reference': fields['username'],
                                          'reason': 'اسم المستخدم موجود في معرض مختلف.'})
                    retained += 1
            elif record_value(record) == record_value(local):
                actions[uid] = 'skip'
            elif fields.get('branch') in preserve:
                actions[uid] = 'skip'
            elif label in HISTORY_ONLY:
                # Existing audit/idempotency history is never overwritten.
                actions[uid] = 'skip'
            elif fields.get('branch') in advance:
                actions[uid] = 'update'
            else:
                actions[uid] = 'conflict'
                conflicts.append({
                    'model': label, 'label': MODEL_LABELS.get(label, label),
                    'reference': str(fields.get('order_number') or fields.get('invoice_number')
                                     or fields.get('sku') or fields.get('name') or record['source_pk'])[:150],
                    'reason': 'السجل يختلف عن الموجود ولا توجد نقطة سابقة مطابقة تسمح بتحديث أرصدته بأمان.',
                })
        # Validate branch ownership before inserting any row, including fields
        # whose ordinary model.save() validation is intentionally bypassed.
        for record in records:
            if actions[record['uid']] == 'skip':
                continue
            model, fields = backup_models()[record['model']], record['fields']
            branch = fields.get('branch')
            for name in getattr(model, 'branch_relations', ()):
                ref = fields.get(name)
                if ref and incoming_by_uid[ref]['fields'].get('branch') != branch:
                    raise BackupError('توجد علاقة بين معرضين مختلفين في النسخة.')
            for name, refs in record['m2m'].items():
                for ref in refs:
                    other_branch = incoming_by_uid[ref]['fields'].get('branch')
                    if branch and other_branch and branch != other_branch:
                        raise BackupError('توجد تسوية أو علاقة متعددة بين معرضين مختلفين.')
        media_plan = _media_plan(manifest, media)
        counts = defaultdict(Counter)
        for record in records:
            counts[record['model']][actions[record['uid']]] += 1
        summary = {
            'created_at': manifest['created_at'], 'archive_id': manifest['archive_id'],
            'rows': [{'model': label, 'label': MODEL_LABELS.get(label, label),
                      'create': c['create'], 'update': c['update'], 'skip': c['skip'], 'conflict': c['conflict']}
                     for label, c in sorted(counts.items())],
            'create': sum(c['create'] for c in counts.values()),
            'update': sum(c['update'] for c in counts.values()),
            'skip': sum(c['skip'] for c in counts.values()),
            'conflict_count': len(conflicts), 'conflicts': conflicts[:100], 'preserved_users': retained,
            'media_count': len(media_plan),
            'media_new': sum(not m['reused'] for m in media_plan.values()),
            'media_reused': sum(m['reused'] for m in media_plan.values()),
            'media_renamed': sum(m['path'] != m['target'] for m in media_plan.values()),
            'missing_media': len(manifest.get('missing_media', [])),
            'branches': [{'code': b['code'], 'name': b['name']} for b in manifest['branches']],
        }
        fingerprint = digest({'data': snapshot_digest(current),
                              'media': sorted((name, item['sha256']) for name, item in media.items())})
        return {'mapped': mapped, 'existing': existing, 'actions': actions, 'summary': summary,
                'fingerprint': fingerprint, 'media': media_plan}


def private_root():
    root = Path(getattr(settings, 'BACKUP_PRIVATE_ROOT', settings.BASE_DIR / 'private_backups')).resolve()
    public_roots = media_roots() + [Path(settings.STATIC_ROOT).resolve()]
    if any(root == p or root.is_relative_to(p) for p in public_roots):
        raise BackupError('مجلد تجهيز النسخ يجب أن يكون خارج مجلدات الصور والملفات العامة.')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def staged_path(job_id):
    return private_root() / f'import-{uuid.UUID(str(job_id))}.zip'


def discard_archive(job_id):
    staged_path(job_id).unlink(missing_ok=True)


def cleanup_archives():
    cutoff = timezone.now() - timedelta(hours=1)
    for job_id in BackupImport.objects.filter(created_at__lt=cutoff).values_list('pk', flat=True):
        discard_archive(job_id)


def stage_upload(upload, user):
    ensure_backup_schema()
    job_id = uuid.uuid4()
    path = staged_path(job_id)
    try:
        total = 0
        with path.open('xb') as destination:
            for chunk in upload.chunks():
                total += len(chunk)
                if total > limits()['upload']:
                    raise BackupError('حجم ملف النسخة يتجاوز حد الرفع المسموح.')
                destination.write(chunk)
        manifest, records = read_archive(path)
        with transaction.atomic(), unscoped():
            plan = plan_merge(manifest, records)
            return BackupImport.objects.create(
                id=job_id, created_by=user, original_name=Path(upload.name).name[:255],
                archive_digest=file_digest(path), preview_digest=plan['fingerprint'], summary=plan['summary'],
            )
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _lock_tables():
    if connection.vendor == 'postgresql':
        tables = sorted({m._meta.db_table for m in backup_models().values()}
                        | {f.remote_field.through._meta.db_table for m in backup_models().values()
                           for f in m._meta.many_to_many})
        with connection.cursor() as cursor:
            cursor.execute('LOCK TABLE ' + ', '.join(connection.ops.quote_name(t) for t in tables)
                           + ' IN SHARE ROW EXCLUSIVE MODE')


def _resolved_fields(record, mapped, media_plan):
    model = backup_models()[record['model']]
    values = {}
    for field in model._meta.concrete_fields:
        if field.primary_key:
            continue
        value = record['fields'][field.name]
        if field.is_relation:
            value = mapped[value][1] if value is not None else None
        elif isinstance(field, models.FileField):
            name = value['path']
            value = media_plan[name]['target'] if name in media_plan else name
            if field.max_length and len(value) > field.max_length:
                raise BackupError('اسم صورة مستعادة يتجاوز طول الحقل؛ لم يطبق الدمج.')
        else:
            value = field.to_python(value)
        values[field.attname] = value
    refs = record.get('refs', {})
    for name in ['object_id', 'server_object_id']:
        if name in refs:
            values[name] = str(mapped[refs[name]][1])
    if 'response_refs' in refs:
        values['response_json'] = deepcopy(values['response_json'])
        for key, uid in refs['response_refs'].items():
            values['response_json'][key] = mapped[uid][1]
    if 'purchase_return_movement' in refs:
        values['reference'] = f"PUR-RET-{mapped[refs['purchase_return_movement']][1]}"
    return values


def _apply_records(records, plan):
    registry, mapped = backup_models(), plan['mapped']
    # Django's PostgreSQL/SQLite foreign keys are initially deferred. Allocate
    # every destination key first, then verify all constraints after all rows
    # exist; this also preserves cyclic/self-referencing category graphs.
    for record in records:
        if plan['actions'][record['uid']] == 'create':
            model = registry[record['model']]
            pk = mapped[record['uid']][1]
            obj = model(pk=pk, **_resolved_fields(record, mapped, plan['media']))
            obj.save_base(raw=True, force_insert=True)
    for record in records:
        if plan['actions'][record['uid']] == 'update':
            registry[record['model']]._base_manager.filter(pk=mapped[record['uid']][1]).update(
                **_resolved_fields(record, mapped, plan['media']))
    for record in records:
        if plan['actions'][record['uid']] in {'create', 'update'}:
            obj = registry[record['model']]._base_manager.get(pk=mapped[record['uid']][1])
            for name, values in record['m2m'].items():
                getattr(obj, name).set([mapped[uid][1] for uid in values])
        label, pk = mapped[record['uid']]
        identity = BackupIdentity.objects.filter(uid=record['uid']).first()
        primary_exists = BackupIdentity.objects.filter(model_label=label, object_pk=str(pk), is_primary=True).exists()
        same_object = bool(identity and identity.model_label == label and identity.object_pk == str(pk))
        primary = bool(same_object and identity.is_primary) or not primary_exists
        BackupIdentity.objects.update_or_create(
            uid=record['uid'], defaults={'model_label': label, 'object_pk': str(pk), 'is_primary': primary})
    with connection.cursor() as cursor:
        for sql in connection.ops.sequence_reset_sql(no_style(), list(registry.values())):
            cursor.execute(sql)


def _install_media(path, plan, created_paths):
    root = Path(settings.MEDIA_ROOT).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path) as archive:
        for item in plan['media'].values():
            if item['reused']:
                continue
            destination = root / safe_name(item['target'])
            if not destination.resolve().is_relative_to(root):
                raise BackupError('مسار صورة الاستعادة خارج مجلد الصور.')
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Existing files are never overwritten, even if another process
            # changed the filesystem between preview and apply.
            try:
                stream = destination.open('xb')
            except FileExistsError:
                if file_digest(destination) == item['sha256']:
                    continue
                raise BackupError('تغير ملف صورة أثناء الدمج؛ أعد رفع النسخة للمعاينة.')
            created_paths.append(destination)
            result = hashlib.sha256()
            with stream, archive.open(f"media/{item['path']}") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b''):
                    stream.write(chunk)
                    result.update(chunk)
            if result.hexdigest() != item['sha256']:
                raise BackupError('تغيرت صورة أثناء الدمج؛ ألغيت العملية.')


def apply_import(job_id, user):
    created_paths = []
    try:
        with unscoped(), transaction.atomic():
            job = BackupImport.objects.select_for_update().get(pk=job_id, created_by=user)
            if job.completed_at:
                return job
            if timezone.now() - job.created_at > timedelta(hours=1):
                raise BackupError('انتهت صلاحية المعاينة. ارفع النسخة من جديد.')
            path = staged_path(job.pk)
            if not path.is_file() or file_digest(path) != job.archive_digest:
                raise BackupError('ملف المعاينة غير متاح أو تغير؛ ارفع النسخة من جديد.')
            # A write obtains SQLite's writer lock before planning. PostgreSQL
            # also locks business tables so ordinary sales cannot race a merge.
            BackupImport.objects.filter(pk=job.pk).update(preview_digest=job.preview_digest)
            _lock_tables()
            manifest, records = read_archive(path)
            plan = plan_merge(manifest, records)
            if plan['fingerprint'] != job.preview_digest:
                raise BackupError('تغيرت البيانات أو الصور بعد المعاينة. ارفع النسخة مجددًا لمراجعة خطة محدثة.')
            if plan['summary']['conflict_count']:
                raise BackupError('توجد تعارضات في النسخة؛ لم يطبق أي جزء من الدمج.')
            _apply_records(records, plan)
            connection.check_constraints(table_names=[m._meta.db_table for m in backup_models().values()])
            _install_media(path, plan, created_paths)
            current, _ = collect_snapshot({key: uid for uid, key in plan['mapped'].items()})
            for branch in manifest['branches']:
                local_pk = plan['mapped'][branch['uid']][1]
                new_digest = branch_digest(current, branch['uid'])
                history = BackupBranchHistory.objects.filter(branch_id=local_pk).first()
                ancestors = set(history.ancestors if history else []) | set(branch['ancestors'])
                if history:
                    ancestors.add(history.digest)
                ancestors.discard(new_digest)
                BackupBranchHistory.objects.update_or_create(
                    branch_id=local_pk, defaults={'digest': new_digest, 'ancestors': sorted(ancestors)})
            from audit.services import log_audit
            log_audit(user=user, action='create', section='settings', model_name='BackupImport',
                      object_id=job.pk, object_repr='دمج نسخة احتياطية',
                      notes=f"إضافة {plan['summary']['create']} سجل وتحديث {plan['summary']['update']} سجل دون إعادة ترحيل حركات.")
            job.completed_at = timezone.now()
            job.summary = plan['summary']
            BackupImport.objects.filter(pk=job.pk).update(completed_at=job.completed_at, summary=job.summary)
        transaction.on_commit(lambda: discard_archive(job.pk))
        return job
    except Exception:
        # Only files created by this attempt are removed. Existing media and
        # preexisting business rows remain untouched on every failure path.
        for path in reversed(created_paths):
            path.unlink(missing_ok=True)
        raise
