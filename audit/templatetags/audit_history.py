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

MODEL_LABELS = {
    'User': 'مستخدم',
    'Product': 'منتج',
    'ProductVariant': 'لون / مقاس',
    'Category': 'تصنيف',
    'Color': 'لون',
    'Size': 'مقاس',
    'Customer': 'عميل',
    'CustomerInteraction': 'متابعة عميل',
    'Order': 'فاتورة بيع',
    'OrderItem': 'صنف فاتورة',
    'Warehouse': 'مخزن',
    'Stock': 'رصيد مخزون',
    'StockBatch': 'دفعة مخزون',
    'StockMovement': 'حركة مخزون',
    'Supplier': 'مورد',
    'PurchaseOrder': 'أمر شراء',
    'PurchaseOrderItem': 'صنف أمر شراء',
    'SalesReturn': 'مرتجع',
    'SalesReturnItem': 'صنف مرتجع',
    'ExchangeItem': 'صنف استبدال',
    'CashAccount': 'حساب مالي',
    'PaymentTransaction': 'حركة مالية',
    'Invoice': 'فاتورة',
    'CompanySettings': 'إعدادات الشركة',
    'SalesRepStockAssignment': 'عهدة مندوب',
    'SalesRepCollection': 'تحصيل مندوب',
}

FIELD_LABELS = {
    'id': 'المعرف',
    'pk': 'المعرف',
    'name': 'الاسم',
    'username': 'اسم المستخدم',
    'first_name': 'الاسم الأول',
    'last_name': 'اسم العائلة',
    'email': 'البريد الإلكتروني',
    'password': 'كلمة المرور',
    'role': 'الدور',
    'phone': 'الهاتف',
    'address': 'العنوان',
    'created_at': 'تاريخ الإنشاء',
    'updated_at': 'تاريخ التحديث',
    'created_by_id': 'أنشئ بواسطة',
    'is_active': 'الحالة',
    'is_staff': 'صلاحية الإدارة',
    'is_superuser': 'مدير النظام',
    'last_login': 'آخر دخول',
    'date_joined': 'تاريخ الانضمام',
    'sku': 'كود المنتج',
    'variant_sku': 'كود اللون / المقاس',
    'barcode': 'الباركود',
    'category_id': 'التصنيف',
    'parent_id': 'التصنيف الأب',
    'description': 'الوصف',
    'material': 'الخامة',
    'season': 'الموسم',
    'retail_price': 'سعر التجزئة',
    'wholesale_price': 'سعر الجملة',
    'cost_price': 'سعر الشراء',
    'sale_price': 'سعر البيع',
    'pieces_per_dozen': 'عدد القطع في الدستة',
    'image': 'الصورة',
    'product_id': 'المنتج',
    'color_id': 'اللون',
    'size_id': 'المقاس',
    'hex_code': 'كود اللون',
    'sort_order': 'ترتيب العرض',
    'customer_type': 'نوع العميل',
    'company_name': 'اسم الشركة',
    'opening_balance': 'الرصيد الافتتاحي',
    'current_balance': 'الرصيد الحالي',
    'credit_limit': 'حد الائتمان',
    'notes': 'ملاحظات',
    'order_number': 'رقم الفاتورة',
    'order_type': 'نوع الفاتورة',
    'document_type': 'نوع المستند',
    'status': 'الحالة',
    'customer_id': 'العميل',
    'warehouse_id': 'المخزن',
    'payment_method': 'طريقة الدفع',
    'wallet_from_number': 'محفظة العميل',
    'wallet_to_number': 'محفظة الشركة',
    'subtotal': 'الإجمالي قبل الخصم',
    'discount': 'الخصم',
    'discount_amount': 'قيمة الخصم',
    'discount_percentage': 'نسبة الخصم',
    'total': 'الإجمالي',
    'paid_amount': 'المدفوع',
    'remaining_amount': 'المتبقي',
    'quantity': 'الكمية',
    'min_quantity': 'حد التنبيه',
    'unit_price': 'سعر الوحدة',
    'original_unit_price': 'السعر الأصلي',
    'final_unit_price': 'السعر النهائي',
    'profit_total': 'إجمالي الربح',
    'gross_profit': 'إجمالي الربح',
    'total_cost': 'إجمالي التكلفة',
    'variant_id': 'اللون / المقاس',
    'from_warehouse_id': 'من مخزن',
    'to_warehouse_id': 'إلى مخزن',
    'movement_type': 'نوع الحركة',
    'note': 'ملاحظة',
    'batch_id': 'دفعة المخزون',
    'remaining_quantity': 'الكمية المتبقية',
    'supplier_id': 'المورد',
    'purchase_number': 'رقم أمر الشراء',
    'order_date': 'تاريخ الطلب',
    'expected_date': 'التاريخ المتوقع',
    'received_date': 'تاريخ الاستلام',
    'total_amount': 'إجمالي المبلغ',
    'return_type': 'نوع المرتجع',
    'refund_amount': 'قيمة الاسترداد',
    'reason': 'السبب',
    'approved_by_id': 'اعتمد بواسطة',
    'completed_by_id': 'أكمل بواسطة',
    'cash_account_id': 'الحساب المالي',
    'account_type': 'نوع الحساب',
    'balance': 'الرصيد',
    'allow_overdraft': 'السحب على المكشوف',
    'transaction_type': 'نوع الحركة المالية',
    'direction': 'الاتجاه',
    'amount': 'المبلغ',
    'transaction_date': 'تاريخ الحركة',
    'related_order_id': 'الفاتورة المرتبطة',
    'related_customer_id': 'العميل المرتبط',
    'related_supplier_id': 'المورد المرتبط',
    'related_sales_rep_id': 'المندوب المرتبط',
    'invoice_number': 'رقم الفاتورة',
    'issued_at': 'تاريخ الإصدار',
}

IGNORED_CHANGE_FIELDS = {
    'updated_at',
    'modified_at',
    'last_login',
}


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
    if field_name in FIELD_LABELS:
        return FIELD_LABELS[field_name]
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
        return 'فارغ'
    if value == '***REDACTED***':
        return 'محجوب'
    if isinstance(value, bool):
        return 'نعم' if value else 'لا'
    return str(value)


def _change_rows(log):
    if log.action == AuditLog.ACTION_DELETE:
        return [{
            'field': 'الحالة',
            'before': 'موجود',
            'after': 'محذوف',
        }]

    model = _model_for_log(log)
    before = log.changes_before or {}
    after = log.changes_after or {}
    keys = sorted((set(before) | set(after)) - IGNORED_CHANGE_FIELDS)
    rows = []
    for key in keys:
        before_value = before.get(key)
        after_value = after.get(key)
        if before_value == after_value:
            continue
        rows.append({
            'field': _field_label(model, key),
            'before': _format_value(before_value),
            'after': _format_value(after_value),
        })
    return rows


def _snapshot_rows(log):
    model = _model_for_log(log)
    snapshot = log.changes_before or {}
    rows = []
    for key in sorted(set(snapshot) - IGNORED_CHANGE_FIELDS):
        rows.append({
            'field': _field_label(model, key),
            'value': _format_value(snapshot.get(key)),
        })
    return rows


@register.filter
def audit_change_rows(log):
    return _change_rows(log)


@register.filter
def audit_deleted_snapshot_rows(log):
    if log.action != AuditLog.ACTION_DELETE:
        return []
    return _snapshot_rows(log)


@register.filter
def audit_model_label(model_name):
    return MODEL_LABELS.get(model_name, model_name or '-')


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
        'empty_message': 'لا يوجد سجل تعديل أو حذف لهذا السجل بعد.',
        'history_logs': [
            {
                'log': log,
                'rows': _change_rows(log),
            }
            for log in logs
        ],
    }
