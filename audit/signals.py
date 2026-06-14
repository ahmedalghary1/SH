from datetime import datetime
from decimal import Decimal

from django.db.models.signals import post_save, pre_delete, pre_save
from django.dispatch import receiver
from django.utils import timezone

from audit.context import get_current_request
from audit.models import AuditLog
from audit.services import get_client_info, log_audit


APP_SECTIONS = {
    'accounts': AuditLog.SECTION_ACCOUNTS,
    'products': AuditLog.SECTION_PRODUCTS,
    'orders': AuditLog.SECTION_ORDERS,
    'inventory': AuditLog.SECTION_INVENTORY,
    'purchases': AuditLog.SECTION_PURCHASES,
    'returns': AuditLog.SECTION_RETURNS,
    'finance': AuditLog.SECTION_FINANCE,
    'customers': AuditLog.SECTION_CUSTOMERS,
    'sales_reps': AuditLog.SECTION_SALES_REPS,
    'settings_app': AuditLog.SECTION_SETTINGS,
    'invoices': AuditLog.SECTION_INVOICES,
}

IGNORED_APP_LABELS = {
    'admin',
    'audit',
    'auth',
    'contenttypes',
    'sessions',
}

SENSITIVE_FIELD_NAMES = {
    'password',
    'token',
    'secret',
    'api_key',
    'access_key',
    'refresh_token',
}


def _should_track(sender):
    return sender._meta.app_label not in IGNORED_APP_LABELS


def _section_for(sender):
    return APP_SECTIONS.get(sender._meta.app_label, sender._meta.app_label[:20])


def _json_value(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime) and timezone.is_aware(value):
        value = timezone.localtime(value)
        return value.isoformat()
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)


def _is_sensitive_field(field):
    field_name = field.name.lower()
    attname = field.attname.lower()
    return any(name in field_name or name in attname for name in SENSITIVE_FIELD_NAMES)


def _snapshot(instance, redact_sensitive=True):
    data = {}
    for field in instance._meta.concrete_fields:
        if redact_sensitive and _is_sensitive_field(field):
            data[field.attname] = '***REDACTED***'
        else:
            data[field.attname] = _json_value(getattr(instance, field.attname))
    return data


def _changed_values(before_compare, after_compare, before_display, after_display):
    before_changes = {}
    after_changes = {}
    for key, before_value in before_compare.items():
        if before_value != after_compare.get(key):
            before_changes[key] = before_display.get(key)
            after_changes[key] = after_display.get(key)
    return before_changes, after_changes


def _request_user_and_client():
    request = get_current_request()
    user = None
    if request and getattr(request, 'user', None) and request.user.is_authenticated:
        user = request.user
    ip_address, user_agent = get_client_info(request)
    return user, ip_address, user_agent


def _write_log(sender, instance, action, before=None, after=None):
    user, ip_address, user_agent = _request_user_and_client()
    log_audit(
        user=user,
        action=action,
        section=_section_for(sender),
        model_name=sender.__name__,
        object_id=instance.pk,
        object_repr=str(instance)[:200],
        changes_before=before,
        changes_after=after,
        ip_address=ip_address,
        user_agent=user_agent,
    )


@receiver(pre_save)
def capture_update_before(sender, instance, raw=False, **kwargs):
    if raw or not _should_track(sender) or not instance.pk:
        return

    previous = sender.objects.filter(pk=instance.pk).first()
    instance._audit_before_snapshot = _snapshot(previous) if previous else None
    instance._audit_before_compare = _snapshot(previous, redact_sensitive=False) if previous else None


@receiver(post_save)
def log_update(sender, instance, created=False, raw=False, **kwargs):
    if raw or created or not _should_track(sender):
        return

    before = getattr(instance, '_audit_before_snapshot', None)
    before_compare = getattr(instance, '_audit_before_compare', None)
    if not before or not before_compare:
        return

    after = _snapshot(instance)
    after_compare = _snapshot(instance, redact_sensitive=False)
    before_changes, after_changes = _changed_values(before_compare, after_compare, before, after)
    if before_changes:
        _write_log(
            sender,
            instance,
            AuditLog.ACTION_UPDATE,
            before=before_changes,
            after=after_changes,
        )


@receiver(pre_delete)
def log_delete(sender, instance, **kwargs):
    if not _should_track(sender):
        return

    _write_log(
        sender,
        instance,
        AuditLog.ACTION_DELETE,
        before=_snapshot(instance),
        after=None,
    )
