"""Check the runtime email configuration without exposing credentials."""
from django.conf import settings
from django.core.mail import get_connection
from django.core.management.base import BaseCommand, CommandError

from config.error_email import delivery_failure_reason, email_configuration, send_diagnostic_email


class Command(BaseCommand):
    help = 'Check error email settings. No message is sent unless --send-test is specified.'

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group()
        group.add_argument('--connect', action='store_true', help='Connect/authenticate to SMTP without sending a message.')
        group.add_argument('--send-test', action='store_true', help='Send one diagnostic message to ERROR_EMAIL_TO.')

    def handle(self, *args, **options):
        configuration = email_configuration()
        self.stdout.write(f"Backend: {configuration['backend']}")
        self.stdout.write(f"Alerts enabled: {configuration['enabled']}; recipients: {len(configuration['recipients'])}")
        if configuration['smtp']:
            self.stdout.write(f'SMTP port: {settings.EMAIL_PORT}; TLS: {settings.EMAIL_USE_TLS}; SSL: {settings.EMAIL_USE_SSL}')
            self.stdout.write(f'SMTP user configured: {bool(settings.EMAIL_HOST_USER)}; password configured: {bool(settings.EMAIL_HOST_PASSWORD)}')
        self.stdout.write('Runtime environment: hosting process variables and private .env; .env.example is not loaded.')
        if not configuration['ready']:
            raise CommandError(' '.join(configuration['issues']))
        if options['connect'] and not configuration['smtp']:
            raise CommandError('--connect requires the SMTP backend.')
        if options['connect'] or options['send_test']:
            connection = None
            try:
                if options['connect']:
                    connection = get_connection(fail_silently=False)
                    connection.open()
                else:
                    send_diagnostic_email()
            except Exception as exc:
                code = getattr(exc, 'smtp_code', '-')
                raise CommandError(f'{delivery_failure_reason(exc)} [{type(exc).__name__}; SMTP {code}]') from None
            finally:
                if connection is not None:
                    connection.close()
            result = 'SMTP connection/authentication succeeded; no message sent.' if options['connect'] else 'Diagnostic message accepted by the mail backend; check the inbox and spam folder.'
            self.stdout.write(self.style.SUCCESS(result))
        else:
            self.stdout.write(self.style.SUCCESS('Email configuration is complete; delivery has not been tested. Use --connect or --send-test explicitly.'))
