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

SECTION_BY_NAMESPACE = {
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
    'settings': AuditLog.SECTION_SETTINGS,
    'invoices': AuditLog.SECTION_INVOICES,
}

SECTION_BY_CONTEXT_KEY = {
    'users': AuditLog.SECTION_ACCOUNTS,
    'products': AuditLog.SECTION_PRODUCTS,
    'variants': AuditLog.SECTION_PRODUCTS,
    'categories': AuditLog.SECTION_PRODUCTS,
    'colors': AuditLog.SECTION_PRODUCTS,
    'sizes': AuditLog.SECTION_PRODUCTS,
    'orders': AuditLog.SECTION_ORDERS,
    'warehouses': AuditLog.SECTION_INVENTORY,
    'stocks': AuditLog.SECTION_INVENTORY,
    'movements': AuditLog.SECTION_INVENTORY,
    'suppliers': AuditLog.SECTION_PURCHASES,
    'purchase_orders': AuditLog.SECTION_PURCHASES,
    'returns': AuditLog.SECTION_RETURNS,
    'transactions': AuditLog.SECTION_FINANCE,
    'accounts': AuditLog.SECTION_FINANCE,
    'customers': AuditLog.SECTION_CUSTOMERS,
    'assignments': AuditLog.SECTION_SALES_REPS,
    'collections': AuditLog.SECTION_SALES_REPS,
    'invoices': AuditLog.SECTION_INVOICES,
}


def _current_object(context):
    for key in CONTEXT_OBJECT_KEYS:
        obj = context.get(key)
        if obj is not None and getattr(obj, 'pk', None):
            return obj
    return None


def _current_section(context, request):
    explicit_section = context.get('audit_section')
    if explicit_section:
        return explicit_section

    resolver_match = getattr(request, 'resolver_match', None)
    namespace = getattr(resolver_match, 'namespace', '') or getattr(resolver_match, 'app_name', '')
    if namespace in SECTION_BY_NAMESPACE:
        return SECTION_BY_NAMESPACE[namespace]

    for key, section in SECTION_BY_CONTEXT_KEY.items():
        if key in context:
            return section
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
    if not _can_view_history(user):
        return {'show_history': False}

    logs = AuditLog.objects.select_related('user').filter(
        action__in=(AuditLog.ACTION_UPDATE, AuditLog.ACTION_DELETE),
    )
    show_object = False
    empty_message = 'لا يوجد سجل تعديل أو حذف لهذا السجل بعد.'

    if obj:
        logs = logs.filter(model_name=obj.__class__.__name__, object_id=str(obj.pk))
    else:
        section = _current_section(context, request)
        if not section:
            return {'show_history': False}
        logs = logs.filter(section=section)
        show_object = True
        empty_message = 'لا يوجد سجل تعديل أو حذف في هذه الصفحة بعد.'

    return {
        'show_history': True,
        'show_object': show_object,
        'empty_message': empty_message,
        'history_logs': [
            {
                'log': log,
                'rows': _change_rows(log),
            }
            for log in logs
        ],
    }
