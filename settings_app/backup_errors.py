import errno
import logging
from uuid import uuid4

from django.db import DatabaseError

from config.request_context import request_id
from .backup_services import BackupError


logger = logging.getLogger('settings_app.backups')


def report_backup_error(request, exc, operation):
    reference = getattr(request, 'request_id', None) or request_id.get()
    if not reference or reference == '-':
        reference = uuid4().hex[:16]
    request.request_id = reference
    logger.error('Backup operation failed operation=%s category=%s', operation, type(exc).__name__,
                 exc_info=(type(exc), exc, exc.__traceback__),
                 extra={'request': request, 'request_id': reference})
    if isinstance(exc, BackupError):
        message, status = str(exc), 400
    elif isinstance(exc, OSError):
        if exc.errno in {errno.ENOSPC, getattr(errno, 'EDQUOT', errno.ENOSPC)}:
            message = 'لا توجد مساحة كافية لتجهيز النسخة الاحتياطية على الخادم.'
        elif isinstance(exc, PermissionError) or exc.errno in {errno.EACCES, errno.EPERM}:
            message = 'لا يملك التطبيق صلاحية قراءة المرفقات أو الكتابة في مجلد تجهيز النسخة على الخادم.'
        else:
            message = 'تعذر قراءة أحد المرفقات أو إنشاء ملف النسخة على الخادم.'
        status = 503
    elif isinstance(exc, DatabaseError):
        code = getattr(exc.__cause__, 'pgcode', '')
        if code in {'42P01', '42703'} or 'no such table' in str(exc).lower() or 'no such column' in str(exc).lower():
            message = 'بنية قاعدة البيانات غير مكتملة. يلزم تطبيق ترحيلات التحديث على الموقع المنشور.'
        elif code == '23505' or 'locked' in str(exc).lower():
            message = 'تزامنت العملية مع كتابة أخرى في قاعدة البيانات. انتظر انتهاء العملية ثم أعد المحاولة.'
        else:
            message = 'تعذر تجهيز النسخة من قاعدة البيانات. راجع اتصال قاعدة الموقع المنشور وسجل الخطأ.'
        status = 503
    else:
        message, status = f'حدث خطأ غير متوقع أثناء تجهيز النسخة ({type(exc).__name__}). راجع رقم المتابعة.', 500
    return {'message': message, 'reference': reference, 'status': status}
