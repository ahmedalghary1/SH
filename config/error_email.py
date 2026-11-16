"""Observable error email delivery, without request bodies, settings or locals."""
import hashlib
import json
import logging
import smtplib
import ssl
import threading
import time
import traceback

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage, get_connection
from django.core.validators import validate_email
from django.utils import timezone

from .log_sanitizer import sanitize_error_text
from .request_context import request_id


_state_lock = threading.Lock()
_last_delivery = {}
_recent_alerts = {}


def _claim(key, seconds):
    now = time.monotonic()
    with _state_lock:
        for stale in [k for k, expiry in _recent_alerts.items() if expiry <= now]:
            _recent_alerts.pop(stale, None)
        if key in _recent_alerts:
            return False
        if len(_recent_alerts) >= 1024:
            _recent_alerts.pop(next(iter(_recent_alerts)))
        _recent_alerts[key] = now + seconds
        return True


def _forget(key):
    with _state_lock:
        _recent_alerts.pop(key, None)


def email_configuration():
    issues = []
    enabled = getattr(settings, 'ERROR_EMAIL_ENABLED', not settings.DEBUG)
    recipients = [str(address).strip() for _name, address in settings.ADMINS if address]
    sender = settings.SERVER_EMAIL or settings.DEFAULT_FROM_EMAIL
    backend = settings.EMAIL_BACKEND
    smtp = backend == 'django.core.mail.backends.smtp.EmailBackend'
    if backend in {'django.core.mail.backends.console.EmailBackend',
                   'django.core.mail.backends.filebased.EmailBackend',
                   'django.core.mail.backends.dummy.EmailBackend'}:
        issues.append('محرك البريد الحالي لا يرسل رسائل فعلية. استخدم محرك SMTP للإرسال.')
    if not enabled:
        issues.append('تنبيهات الأخطاء البريدية معطلة في إعدادات التشغيل.')
    if not recipients:
        issues.append('لم يحدد بريد لاستقبال الأخطاء في ERROR_EMAIL_TO.')
    if not sender:
        issues.append('لم يحدد بريد المرسل في SERVER_EMAIL أو EMAIL_HOST_USER.')
    for address in [*recipients, sender]:
        if not address:
            continue
        try:
            validate_email(address)
        except ValidationError:
            issues.append('إحدى صيغ عناوين البريد غير صحيحة.')
            break
    if smtp:
        if not settings.EMAIL_HOST:
            issues.append('عنوان خادم SMTP غير مضبوط.')
        if settings.EMAIL_USE_TLS and settings.EMAIL_USE_SSL:
            issues.append('لا يمكن تفعيل EMAIL_USE_TLS وEMAIL_USE_SSL معًا.')
        if not isinstance(settings.EMAIL_PORT, int) or not 1 <= settings.EMAIL_PORT <= 65535:
            issues.append('رقم منفذ SMTP غير صحيح.')
        if settings.EMAIL_HOST_USER and not settings.EMAIL_HOST_PASSWORD:
            issues.append('كلمة مرور SMTP غير مضبوطة في ملف .env الخاص على الخادم.')
        if settings.EMAIL_HOST not in {'localhost', '127.0.0.1', '::1'} and not settings.EMAIL_HOST_USER:
            issues.append('اسم مستخدم SMTP غير مضبوط.')
    return {'enabled': enabled, 'ready': not issues, 'issues': issues,
            'smtp': smtp, 'backend': backend, 'recipients': recipients, 'sender': sender}


def delivery_failure_reason(exc):
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return 'رفض خادم SMTP تسجيل الدخول. راجع اسم المستخدم وكلمة مرور التطبيق.'
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return 'رفض خادم SMTP عنوان المستلم.'
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return 'رفض خادم SMTP عنوان المرسل.'
    if isinstance(exc, ssl.SSLError):
        return 'تعذر تأمين اتصال SMTP. راجع المنفذ وإعدادات TLS وSSL وشهادة الخادم.'
    if isinstance(exc, TimeoutError):
        return 'انتهت مهلة اتصال SMTP؛ قد تمنع الاستضافة الاتصال بخادم البريد.'
    if isinstance(exc, OSError):
        return 'تعذر الاتصال بخادم SMTP. راجع عنوانه والمنفذ وسياسة اتصال الاستضافة.'
    if isinstance(exc, smtplib.SMTPException):
        return 'رفض خادم SMTP الإرسال؛ راجع تفاصيل الخطأ في سجل الأخطاء.'
    return 'تعذر إرسال تنبيه البريد؛ راجع إعداد البريد وسجل الأخطاء.'


def _remember(status, reference, reason=''):
    with _state_lock:
        _last_delivery.clear()
        _last_delivery.update(status=status, reference=reference,
                              reason=reason, at=timezone.now().isoformat())


def email_status():
    configuration = email_configuration()
    with _state_lock:
        last = dict(_last_delivery)
    return {'ready': configuration['ready'], 'issues': configuration['issues'],
            'last_failed': last.get('status') == 'failed', 'last_reason': last.get('reason', ''),
            'log_destination': 'errors.log' if getattr(settings, 'LOG_TO_FILE', False) else 'سجل تطبيق Python في الاستضافة'}


def send_diagnostic_email():
    configuration = email_configuration()
    if not configuration['ready']:
        raise ValueError(' '.join(configuration['issues']))
    return _send('[SH ERP] اختبار تنبيهات الأخطاء',
                 'هذه رسالة اختبار لإعداد تنبيهات أخطاء نظام SH. لا تحتوي بيانات عملاء أو نسخة احتياطية.',
                 configuration)


def _send(subject, body, configuration):
    connection = get_connection(fail_silently=False)
    message = EmailMessage(subject=subject, body=body, from_email=configuration['sender'],
                           to=configuration['recipients'], connection=connection)
    try:
        sent = message.send(fail_silently=False)
        if sent != 1:
            raise RuntimeError('Email backend did not accept the error notification')
        return sent
    finally:
        connection.close()


class ErrorEmailHandler(logging.Handler):
    def emit(self, record):
        # This logger has no mail handler and never propagates to root.
        diagnostic = logging.getLogger('error_alerts')
        reference = getattr(record, 'request_id', None) or request_id.get()
        configuration = email_configuration()
        request = getattr(record, 'request', None)
        path = getattr(request, 'path', '')
        event = [record.name, record.getMessage(), path,
                 record.exc_info[0].__name__ if record.exc_info and record.exc_info[0] else '',
                 configuration['enabled'], settings.EMAIL_BACKEND, settings.EMAIL_HOST,
                 bool(settings.EMAIL_HOST_PASSWORD)]
        key = 'sh-error-email-' + hashlib.sha256(json.dumps(event, default=str).encode()).hexdigest()
        claimed = False
        try:
            timeout = max(1, int(getattr(settings, 'ERROR_EMAIL_REPEAT_SECONDS', 300)))
            if reference != '-' and not _claim('request-' + reference, timeout):
                return
            claimed = _claim(key, timeout)
            if not claimed:
                return
            if not configuration['ready']:
                reason = ' '.join(configuration['issues'])
                _remember('disabled', reference, reason)
                diagnostic.error('ERROR_EMAIL_NOT_READY request=%s reason=%s', reference, reason)
                return
            body = [f'Reference: {reference}', f'Time: {timezone.now().isoformat()}',
                    f'Logger: {record.name}', f'Level: {record.levelname}',
                    f'Operation: {sanitize_error_text(record.getMessage())[:2000]}']
            if request:
                body.append(f'Request: {request.method} {sanitize_error_text(path)}')
            if record.exc_info:
                body.append(sanitize_error_text(''.join(traceback.format_exception(*record.exc_info)))[:24000])
            prefix = getattr(settings, 'EMAIL_SUBJECT_PREFIX', '[SH ERP] ')
            subject = f'{prefix}{record.levelname}: {record.name} [{reference}]'.replace('\r', '').replace('\n', '')
            _send(subject[:220], '\n\n'.join(body), configuration)
            _remember('sent', reference)
            diagnostic.info('ERROR_EMAIL_SENT request=%s', reference)
        except Exception as exc:
            if claimed:
                try:
                    _forget(key)
                except Exception:
                    pass
            reason = delivery_failure_reason(exc)
            _remember('failed', reference, reason)
            diagnostic.error('ERROR_EMAIL_SEND_FAILED request=%s reason=%s error=%s smtp_code=%s',
                             reference, reason, type(exc).__name__, getattr(exc, 'smtp_code', '-'))
