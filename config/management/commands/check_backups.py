"""Exercise the same backup builder used by the website, on the hosting runtime."""
import tempfile
from types import SimpleNamespace
from uuid import uuid4

from django.core.management.base import BaseCommand, CommandError

from settings_app.backup_errors import report_backup_error
from settings_app.backup_services import build_backup, ensure_backup_schema, limits, read_archive


class Command(BaseCommand):
    help = 'Check backup prerequisites; --create builds and validates a temporary ZIP without importing data.'

    def add_arguments(self, parser):
        parser.add_argument('--create', action='store_true', help='Build and validate a temporary full backup; it is deleted after validation.')

    def handle(self, *args, **options):
        reference = uuid4().hex[:16]
        self.stdout.write(f'Reference: {reference}')
        try:
            ensure_backup_schema()
            maximum = limits()
            with tempfile.TemporaryFile() as probe:
                probe.write(b'backup storage probe')
                probe.flush()
            self.stdout.write(f"Migrations and temporary storage: OK; record limit: {maximum['records']}")
            if options['create']:
                with build_backup() as stream:
                    manifest, records = read_archive(stream)
                    self.stdout.write(self.style.SUCCESS(f"ZIP verified: {len(records)} records; {len(manifest['media'])} media files; {len(manifest['missing_media'])} missing file references."))
            else:
                self.stdout.write('Run --create to check the current data and media through the full ZIP generation path.')
        except Exception as exc:
            request = SimpleNamespace(request_id=reference, path='management/check_backups', method='COMMAND')
            failure = report_backup_error(request, exc, 'diagnostic')
            raise CommandError(f"{failure['message']} [Reference: {reference}]") from None
