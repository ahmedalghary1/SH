"""Real browser backup download/upload/confirmation, using disposable data only."""
from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import patch
from wsgiref.simple_server import make_server, WSGIRequestHandler
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    with tempfile.TemporaryDirectory(prefix='sh-backup-browser-') as temporary, ExitStack() as cleanup:
        task_root = Path(temporary)
        os.environ.update(
            DJANGO_SETTINGS_MODULE='config.settings', DB_ENGINE='sqlite',
            SQLITE_PATH=str(task_root / 'browser.sqlite3'), DEBUG='True',
            ALLOWED_HOSTS='127.0.0.1,localhost,testserver', LOG_TO_FILE='False',
            MEDIA_ROOT=str(task_root / 'media'), MEDIA_FALLBACK_ROOTS=str(task_root / 'empty-media'),
            BACKUP_PRIVATE_ROOT=str(task_root / 'private'), DJANGO_ALLOW_ASYNC_UNSAFE='true',
        )
        import django
        django.setup()
        from django.contrib.staticfiles.handlers import StaticFilesHandler
        from django.core.management import call_command
        from django.core.wsgi import get_wsgi_application
        from django.db import connections
        from django.test import Client
        from django.test import override_settings
        from accounts.models import User
        from products.models import Product
        from settings_app.backup_services import BackupError
        from playwright.sync_api import sync_playwright
        cleanup.callback(connections.close_all)
        isolated_media = override_settings(MEDIA_FALLBACK_ROOTS=[])
        isolated_media.enable()
        cleanup.callback(isolated_media.disable)
        call_command('migrate', interactive=False, verbosity=0)
        user = User.objects.create_superuser(username='browser-backup-admin', password='test-password')
        Product.objects.create(name='Browser backup product', sku='BROWSER-BACKUP')
        media = task_root / 'media'
        media.mkdir()
        (media / 'attachment.txt').write_text('all attachments are included', encoding='utf-8')
        client = Client()
        client.force_login(user)

        class QuietHandler(WSGIRequestHandler):
            def log_message(self, *unused):
                pass

        application = StaticFilesHandler(get_wsgi_application())
        slow_download, fail_download = threading.Event(), threading.Event()

        def test_application(environ, start_response):
            if environ.get('PATH_INFO') == '/settings/backups/download/':
                if slow_download.is_set():
                    time.sleep(9)
                if fail_download.is_set():
                    with patch('settings_app.backup_views.build_backup', side_effect=BackupError('تعذر تجهيز النسخة للاختبار')):
                        return application(environ, start_response)
            return application(environ, start_response)

        server = make_server('127.0.0.1', 0, test_application, handler_class=QuietHandler)

        def serve():
            try:
                server.serve_forever()
            finally:
                connections.close_all()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        cleanup.callback(server.server_close)
        cleanup.callback(thread.join)
        cleanup.callback(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}'
        screenshots = ROOT / 'build' / 'backup-browser'
        screenshots.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright, ExitStack() as browser_cleanup:
            browser = playwright.chromium.launch(headless=True)
            browser_cleanup.callback(browser.close)
            browser_cleanup.callback(connections.close_all)
            context = browser.new_context(viewport={'width': 1440, 'height': 1000}, accept_downloads=True)
            context.add_cookies([dict(name='sessionid', value=client.cookies['sessionid'].value, url=base)])
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/settings/', wait_until='networkidle')
            page.locator('a[href="/settings/backups/"]').click()
            page.wait_for_selector('input[type=file]')
            page.evaluate('() => navigator.serviceWorker.ready')
            if not page.evaluate('!!navigator.serviceWorker.controller'):
                page.reload(wait_until='networkidle')
            page.wait_for_function('!!navigator.serviceWorker.controller')
            page.screenshot(path=str(screenshots / 'backups-desktop.png'), full_page=True)
            slow_download.set()
            with page.expect_download() as downloaded:
                page.locator('a[href="/settings/backups/download/"]').click()
            archive = task_root / 'download.zip'
            downloaded.value.save_as(str(archive))
            with zipfile.ZipFile(archive) as zipped:
                assert zipped.testzip() is None
                assert zipped.read('media/attachment.txt') == b'all attachments are included'
            slow_download.clear()
            fail_download.set()
            unexpected = []
            page.on('download', lambda download: unexpected.append(download.suggested_filename))
            page.locator('a[href="/settings/backups/download/"]').click()
            page.wait_for_selector('[data-backup-error]:has-text("تعذر تجهيز النسخة للاختبار")')
            assert page.locator('[data-backup-error] code').inner_text().strip()
            assert not unexpected, unexpected
            page.screenshot(path=str(screenshots / 'download-error.png'), full_page=True)
            fail_download.clear()
            page.locator('[data-backup-error] a').click()
            page.wait_for_selector('input[type=file]')
            page.locator('input[type=file]').set_input_files(str(archive))
            page.locator('button[type=submit]').filter(has_text='رفع').click()
            page.wait_for_selector('input[name=confirm]')
            assert page.locator('main').inner_text().count('معاينة') > 0
            page.screenshot(path=str(screenshots / 'preview-desktop.png'), full_page=True)
            for width in [1440, 980, 768, 390]:
                page.set_viewport_size({'width': width, 'height': 900})
                page.wait_for_timeout(350)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), width
            page.screenshot(path=str(screenshots / 'preview-mobile.png'), full_page=True)
            page.locator('input[name=confirm]').check()
            page.locator('button[type=submit]').filter(has_text='تأكيد').click()
            page.wait_for_selector('h1:has-text("اكتمل دمج النسخة")')
            assert Product.all_objects.filter(sku='BROWSER-BACKUP').count() == 1
            assert not errors, errors
            print('PASS: real Chromium controlled by service worker, download longer than eight seconds, valid ZIP contents, visible failures without HTML downloads, upload/merge, four viewport widths, no JS errors')


if __name__ == '__main__':
    main()
