from django import template
from django.apps import apps

from audit.models import AuditLog


register = template.Library()


CONTEXT_OBJECT_KEYS = (
    'audit_object',
    'object',
    'product',
    'variant',
    'customer',
    'supplier',
    'order',
    'purchase_order',
    'sales_return',
    'account',
    'invoice',
    'warehouse',
    'stock',
)


def _current_object(context):
    for key in CONTEXT_OBJECT_KEYS:
        obj = context.get(key)
        if obj is not None and getattr(obj, 'pk', None):
            return obj
    return None


def _can_view_history(user):
    return bool(
        getattr(user, 'is_authenticated', False)
        and (getattr(user, 'is_manager', False) or getattr(user, 'is_superuser', False))
    )


def _model_for_log(log):
    for model in apps.get_models():
        if model.__name__ == log.model_name:
            return model
    return None


def _field_label(model, field_name):
    if not model:
        return field_name
    try:
        field = model._meta.get_field(field_name)
    except Exception:
        return field_name
    return str(field.verbose_name or field_name)


def _format_value(value):
    if value is None:
        return '-'
    if value == '':
        return '(empty)'
    if isinstance(value, bool):
        return 'Yes' if value else 'No'
    return str(value)


def _change_rows(log):
    model = _model_for_log(log)
    before = log.changes_before or {}
    after = log.changes_after or {}
    keys = sorted(set(before) | set(after))
    rows = []
    for key in keys:
        rows.append({
            'field': _field_label(model, key),
            'before': _format_value(before.get(key)),
            'after': _format_value(after.get(key)),
        })
    return rows


@register.filter
def audit_change_rows(log):
    return _change_rows(log)


@register.inclusion_tag('audit/object_history.html', takes_context=True)
def current_page_audit_history(context, limit=20):
    request = context.get('request')
    user = getattr(request, 'user', None)
    obj = _current_object(context)
    if not obj or not _can_view_history(user):
        return {'show_history': False}

    logs = AuditLog.objects.select_related('user').filter(
        model_name=obj.__class__.__name__,
        object_id=str(obj.pk),
        action__in=(AuditLog.ACTION_UPDATE, AuditLog.ACTION_DELETE),
    ).order_by('-created_at')[:limit]

    return {
        'show_history': True,
        'history_logs': [
            {
                'log': log,
                'rows': _change_rows(log),
            }
            for log in logs
        ],
    }
