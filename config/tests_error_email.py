import io
import logging
import smtplib
import sys
from unittest.mock import Mock, patch

from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import RequestFactory, SimpleTestCase, override_settings

from config import error_email
from config.log_sanitizer import SanitizingFilter, SanitizingFormatter


@override_settings(ERROR_EMAIL_ENABLED=True, ERROR_EMAIL_REPEAT_SECONDS=300,
                   EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
                   ADMINS=[('Admin', 'admin@example.test')], SERVER_EMAIL='system@example.test',
                   EMAIL_HOST_PASSWORD='private-mail-password', SECRET_KEY='private-django-secret')
class ErrorEmailTests(SimpleTestCase):
    def setUp(self):
        error_email._recent_alerts.clear()
        error_email._last_delivery.clear()
        mail.get_connection()
        mail.outbox.clear()
        self.addCleanup(error_email._recent_alerts.clear)
        self.addCleanup(error_email._last_delivery.clear)

    def record(self, reference='test-reference', exception=None):
        request = RequestFactory().post('/settings/backups/download/?token=private-query',
                                        {'password': 'private-post-body'})
        request.COOKIES['sessionid'] = 'private-session-cookie'
        info = None
        if exception is not None:
            try:
                raise exception
            except Exception:
                info = sys.exc_info()
        record = logging.LogRecord('settings_app.backups', logging.ERROR, __file__, 1,
                                   'Backup operation failed operation=download', (), info)
        record.request = request
        record.request_id = reference
        return record

    def test_email_contains_reference_and_safe_traceback_without_request_secrets(self):
        record = self.record(exception=ValueError('private-mail-password private-django-secret token=abc'))
        error_email.ErrorEmailHandler().emit(record)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ['admin@example.test'])
        self.assertIn('test-reference', message.subject)
        self.assertIn('ValueError', message.body)
        self.assertIn('POST /settings/backups/download/', message.body)
        self.assertIn('REDACTED', message.body)
        for secret in ['private-query', 'private-post-body', 'private-session-cookie',
                       'private-mail-password', 'private-django-secret', 'token=abc']:
            self.assertNotIn(secret, message.body)
        self.assertFalse(error_email.email_status()['last_failed'])

    def test_same_request_and_repeated_event_do_not_send_duplicate_messages(self):
        handler = error_email.ErrorEmailHandler()
        handler.emit(self.record())
        other = self.record()
        other.msg = 'Internal Server Error: /settings/backups/download/'
        handler.emit(other)
        handler.emit(self.record(reference='second-request'))
        self.assertEqual(len(mail.outbox), 1)

    def test_django_response_log_uses_request_reference_after_context_is_reset(self):
        handler = error_email.ErrorEmailHandler()
        handler.emit(self.record())
        later = self.record()
        later.request.request_id = later.request_id
        del later.request_id
        later.name = 'django.request'
        later.msg = 'Internal Server Error: /settings/backups/download/'
        SanitizingFilter().filter(later)
        self.assertEqual(later.request_id, 'test-reference')
        handler.emit(later)
        self.assertEqual(len(mail.outbox), 1)

    def test_configuration_exception_cannot_break_the_original_error_response(self):
        with patch('config.error_email.email_configuration', side_effect=ValueError('private-mail-password')):
            with self.assertLogs('error_alerts', 'ERROR') as logs:
                error_email.ErrorEmailHandler().emit(self.record())
        self.assertIn('ERROR_EMAIL_SEND_FAILED', '\n'.join(logs.output))
        self.assertNotIn('private-mail-password', '\n'.join(logs.output))

    def test_smtp_authentication_failure_is_visible_and_does_not_raise(self):
        failure = smtplib.SMTPAuthenticationError(535, b'private-mail-password SMTP rejection')
        with patch('config.error_email.EmailMessage.send', side_effect=failure), self.assertLogs('error_alerts', 'ERROR') as logs:
            error_email.ErrorEmailHandler().emit(self.record())
        self.assertTrue(error_email.email_status()['last_failed'])
        self.assertIn('تسجيل الدخول', error_email.email_status()['last_reason'])
        self.assertIn('ERROR_EMAIL_SEND_FAILED', '\n'.join(logs.output))
        self.assertIn('535', '\n'.join(logs.output))
        self.assertNotIn('private-mail-password', '\n'.join(logs.output))
        # A subsequent request can retry delivery after a transient failure.
        error_email.ErrorEmailHandler().emit(self.record(reference='retry-request'))
        self.assertEqual(len(mail.outbox), 1)

    def test_backend_returning_zero_is_a_reported_delivery_failure(self):
        with patch('config.error_email.EmailMessage.send', return_value=0), self.assertLogs('error_alerts', 'ERROR'):
            error_email.ErrorEmailHandler().emit(self.record())
        self.assertTrue(error_email.email_status()['last_failed'])

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend',
                       EMAIL_HOST='smtp.example.test', EMAIL_HOST_USER='system@example.test', EMAIL_HOST_PASSWORD='')
    def test_missing_password_is_reported_without_attempting_network(self):
        with patch('config.error_email.get_connection') as connect, self.assertLogs('error_alerts', 'ERROR') as logs:
            error_email.ErrorEmailHandler().emit(self.record())
        connect.assert_not_called()
        self.assertFalse(error_email.email_status()['ready'])
        self.assertIn('كلمة مرور SMTP', ' '.join(error_email.email_status()['issues']))
        self.assertIn('ERROR_EMAIL_NOT_READY', '\n'.join(logs.output))

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.dummy.EmailBackend')
    def test_non_delivery_backend_is_not_reported_ready(self):
        self.assertFalse(error_email.email_configuration()['ready'])

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend',
                       EMAIL_HOST='smtp.example.test', EMAIL_HOST_USER='system@example.test',
                       EMAIL_USE_TLS=True, EMAIL_USE_SSL=True)
    def test_conflicting_tls_flags_are_detected(self):
        self.assertFalse(error_email.email_configuration()['ready'])

    def test_configured_secrets_in_exception_tracebacks_are_redacted_in_logs(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(SanitizingFormatter('{request_id} {message}', style='{'))
        handler.addFilter(SanitizingFilter())
        handler.handle(self.record(exception=ValueError('private-mail-password private-django-secret')))
        self.assertIn('test-reference', stream.getvalue())
        self.assertIn('ValueError', stream.getvalue())
        self.assertIn('REDACTED', stream.getvalue())
        self.assertNotIn('private-mail-password', stream.getvalue())
        self.assertNotIn('private-django-secret', stream.getvalue())

    def test_email_command_is_non_sending_by_default(self):
        output = io.StringIO()
        call_command('check_error_email', stdout=output)
        self.assertEqual(mail.outbox, [])
        self.assertIn('delivery has not been tested', output.getvalue())
        self.assertNotIn('private-mail-password', output.getvalue())

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend',
                       EMAIL_HOST='smtp.example.test', EMAIL_HOST_USER='system@example.test')
    def test_connect_command_authenticates_without_sending(self):
        connection = Mock()
        with patch('config.management.commands.check_error_email.get_connection', return_value=connection):
            output = io.StringIO()
            call_command('check_error_email', connect=True, stdout=output)
        connection.open.assert_called_once()
        connection.close.assert_called_once()
        connection.send_messages.assert_not_called()
        self.assertEqual(mail.outbox, [])
        self.assertNotIn('private-mail-password', output.getvalue())

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend',
                       EMAIL_HOST='smtp.example.test', EMAIL_HOST_USER='system@example.test')
    def test_connect_command_failure_reports_reason_without_smtp_response_secrets(self):
        connection = Mock()
        connection.open.side_effect = smtplib.SMTPAuthenticationError(535, b'private-mail-password')
        with patch('config.management.commands.check_error_email.get_connection', return_value=connection):
            with self.assertRaises(CommandError) as failure:
                call_command('check_error_email', connect=True, stdout=io.StringIO())
        self.assertIn('535', str(failure.exception))
        self.assertNotIn('private-mail-password', str(failure.exception))

    def test_explicit_diagnostic_message_uses_configured_recipients(self):
        call_command('check_error_email', send_test=True, stdout=io.StringIO())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['admin@example.test'])
        self.assertIn('اختبار', mail.outbox[0].subject)
