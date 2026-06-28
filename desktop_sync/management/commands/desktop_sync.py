from django.core.management.base import BaseCommand, CommandError

from desktop_sync.models import DesktopSyncConfig, SyncOutbox
from desktop_sync.services import login_remote, pull_remote, push_pending, sync_once


class Command(BaseCommand):
    help = 'Manage the SH desktop offline/online sync client.'

    def add_arguments(self, parser):
        parser.add_argument('action', choices=['login', 'pull', 'push', 'sync', 'status'])
        parser.add_argument('--url', default='')
        parser.add_argument('--username', default='')
        parser.add_argument('--password', default='')

    def handle(self, *args, **options):
        action = options['action']
        try:
            if action == 'login':
                if not options['username'] or not options['password']:
                    raise CommandError('--username and --password are required for login')
                login_remote(options['username'], options['password'], options.get('url') or None)
                self.stdout.write(self.style.SUCCESS('Remote login succeeded.'))
            elif action == 'pull':
                payload = pull_remote()
                self.stdout.write(self.style.SUCCESS(f"Pulled remote data: {', '.join(sorted(payload.keys()))}"))
            elif action == 'push':
                results = push_pending()
                self.stdout.write(self.style.SUCCESS(f'Pushed {len(results)} operation(s).'))
            elif action == 'sync':
                result = sync_once()
                self.stdout.write(self.style.SUCCESS(str(result)))
            elif action == 'status':
                config = DesktopSyncConfig.load()
                pending = SyncOutbox.objects.filter(status=SyncOutbox.STATUS_PENDING).count()
                failed = SyncOutbox.objects.filter(status__in=[SyncOutbox.STATUS_FAILED, SyncOutbox.STATUS_CONFLICT]).count()
                self.stdout.write(f'Remote API: {config.normalized_api_url}')
                self.stdout.write(f'User: {config.username or "-"}')
                self.stdout.write(f'Last pull: {config.last_pull_at or "-"}')
                self.stdout.write(f'Last push: {config.last_push_at or "-"}')
                self.stdout.write(f'Pending: {pending}')
                self.stdout.write(f'Failed/conflict: {failed}')
                self.stdout.write(f'Last error: {config.last_error or "-"}')
        except Exception as exc:
            raise CommandError(str(exc)) from exc
