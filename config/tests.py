import io
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, RequestFactory, TestCase, override_settings

from config.log_sanitizer import SanitizingFilter, sanitize
from config.ratelimit import RateLimitExceeded, get_client_ip, rate_limit

User = get_user_model()


# ================================================================== #
#  Rate Limit Tests (existing — preserved)                           #
# ================================================================== #

class RateLimitTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_get_client_ip_from_remote_addr(self):
        request = self.factory.get('/')
        request.META['REMOTE_ADDR'] = '192.168.1.1'
        self.assertEqual(get_client_ip(request), '192.168.1.1')

    def test_get_client_ip_from_x_forwarded_for(self):
        request = self.factory.get('/')
        request.META['HTTP_X_FORWARDED_FOR'] = '10.0.0.1, 192.168.1.1'
        self.assertEqual(get_client_ip(request), '10.0.0.1')

    def test_rate_limit_allows_requests_within_limit(self):
        request = self.factory.get('/')
        request.META['REMOTE_ADDR'] = '192.168.1.2'
        for _ in range(5):
            result = rate_limit(request, 'test', max_requests=10, period=60)
            self.assertTrue(result)

    def test_rate_limit_blocks_requests_over_limit(self):
        request = self.factory.get('/')
        request.META['REMOTE_ADDR'] = '192.168.1.3'
        for _ in range(10):
            rate_limit(request, 'test', max_requests=10, period=60)
        with self.assertRaises(RateLimitExceeded):
            rate_limit(request, 'test', max_requests=10, period=60)

    def test_rate_limit_different_keys_are_independent(self):
        request = self.factory.get('/')
        request.META['REMOTE_ADDR'] = '192.168.1.4'
        for _ in range(10):
            rate_limit(request, 'test1', max_requests=10, period=60)
        result = rate_limit(request, 'test2', max_requests=10, period=60)
        self.assertTrue(result)


# ================================================================== #
#  Log Sanitizer Tests                                               #
# ================================================================== #

class LogSanitizerTests(TestCase):

    # --- sanitize(dict) ---

    def test_sanitize_dict_masks_password(self):
        result = sanitize({'username': 'ali', 'password': 'secret123'})
        self.assertEqual(result['password'], '***REDACTED***')
        self.assertEqual(result['username'], 'ali')

    def test_sanitize_dict_masks_token(self):
        result = sanitize({'token': 'abc123', 'data': 'ok'})
        self.assertEqual(result['token'], '***REDACTED***')
        self.assertEqual(result['data'], 'ok')

    def test_sanitize_dict_masks_authorization(self):
        result = sanitize({'authorization': 'Bearer xyz'})
        self.assertEqual(result['authorization'], '***REDACTED***')

    def test_sanitize_dict_masks_cookie(self):
        result = sanitize({'cookie': 'sessionid=abc'})
        self.assertEqual(result['cookie'], '***REDACTED***')

    def test_sanitize_dict_masks_card_number(self):
        result = sanitize({'card_number': '4111111111111111', 'amount': '100'})
        self.assertEqual(result['card_number'], '***REDACTED***')
        self.assertEqual(result['amount'], '100')

    def test_sanitize_dict_masks_national_id(self):
        result = sanitize({'national_id': '29901011234567'})
        self.assertEqual(result['national_id'], '***REDACTED***')

    def test_sanitize_dict_masks_nested(self):
        result = sanitize({'user': {'password': 'pw', 'name': 'test'}})
        self.assertEqual(result['user']['password'], '***REDACTED***')
        self.assertEqual(result['user']['name'], 'test')

    def test_sanitize_dict_leaves_safe_keys(self):
        result = sanitize({'order_id': '42', 'status': 'paid', 'amount': 500})
        self.assertEqual(result['order_id'], '42')
        self.assertEqual(result['status'], 'paid')
        self.assertEqual(result['amount'], 500)

    def test_sanitize_list(self):
        result = sanitize([{'password': 'pw'}, {'username': 'ali'}])
        self.assertEqual(result[0]['password'], '***REDACTED***')
        self.assertEqual(result[1]['username'], 'ali')

    # --- sanitize(str) ---

    def test_sanitize_string_masks_kv_password(self):
        result = sanitize('password=mysecret&user=ali')
        self.assertIn('***REDACTED***', result)
        self.assertNotIn('mysecret', result)
        self.assertIn('user=ali', result)

    def test_sanitize_string_masks_token_equals(self):
        result = sanitize('token=abc123&action=login')
        self.assertIn('***REDACTED***', result)
        self.assertNotIn('abc123', result)

    def test_sanitize_string_safe_text_unchanged(self):
        result = sanitize('order 42 confirmed for customer Ali')
        self.assertEqual(result, 'order 42 confirmed for customer Ali')

    # --- SanitizingFilter ---

    def test_sanitizing_filter_cleans_record_msg(self):
        import logging
        record = logging.LogRecord(
            name='test', level=logging.WARNING, pathname='',
            lineno=0, msg='password=secret123', args=None, exc_info=None,
        )
        f = SanitizingFilter()
        f.filter(record)
        self.assertNotIn('secret123', record.msg)
        self.assertIn('***REDACTED***', record.msg)

    def test_sanitizing_filter_cleans_dict_args_directly(self):
        """Test that SanitizingFilter.filter sanitizes a dict passed as args."""
        import logging
        # Create a record with no args first, then set args manually to avoid
        # Python 3.14 LogRecord constructor issue with dict args.
        record = logging.LogRecord(
            name='test', level=logging.INFO, pathname='',
            lineno=0, msg='user data', args=None, exc_info=None,
        )
        record.args = {'password': 'pw123', 'user': 'ali'}
        f = SanitizingFilter()
        f.filter(record)
        self.assertEqual(record.args['password'], '***REDACTED***')
        self.assertEqual(record.args['user'], 'ali')

    def test_sanitizing_filter_always_returns_true(self):
        import logging
        record = logging.LogRecord(
            name='test', level=logging.INFO, pathname='',
            lineno=0, msg='safe message', args=None, exc_info=None,
        )
        result = SanitizingFilter().filter(record)
        self.assertTrue(result)


# ================================================================== #
#  Health Check Tests                                                #
# ================================================================== #

class HealthCheckTests(TestCase):

    def test_health_check_returns_200_when_db_ok(self):
        response = self.client.get('/health/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn(data['status'], ('ok', 'degraded'))

    @override_settings(DEBUG=True)
    def test_health_check_debug_returns_checks_detail(self):
        response = self.client.get('/health/')
        data = response.json()
        # In DEBUG mode we should see the 'checks' key
        self.assertIn('checks', data)
        self.assertIn('database', data['checks'])
        self.assertIn('media', data['checks'])
        self.assertIn('disk', data['checks'])
        self.assertIn('migrations', data['checks'])

    @override_settings(DEBUG=False)
    def test_health_check_production_hides_detail(self):
        response = self.client.get('/health/')
        data = response.json()
        # In production: no 'checks' key exposed
        self.assertNotIn('checks', data)
        self.assertIn('status', data)
        self.assertIn('timestamp', data)

    @override_settings(DEBUG=True)
    def test_health_check_db_ok_status(self):
        response = self.client.get('/health/')
        data = response.json()
        self.assertEqual(data['checks']['database']['status'], 'ok')

    @override_settings(DEBUG=True)
    def test_health_check_disk_present(self):
        response = self.client.get('/health/')
        data = response.json()
        disk = data['checks']['disk']
        self.assertIn(disk['status'], ('ok', 'warning'))

    @patch('config.urls._check_database', return_value=('error', 'Connection refused'))
    def test_health_check_returns_503_on_db_error(self, mock_db):
        response = self.client.get('/health/')
        self.assertEqual(response.status_code, 503)
        data = response.json()
        self.assertEqual(data['status'], 'error')


# ================================================================== #
#  Backup Command Tests                                              #
# ================================================================== #

class BackupCommandTests(TestCase):
    """
    Tests import the Command class directly because 'config' is not in
    INSTALLED_APPS (it is the project config module, not a Django app),
    so call_command() cannot discover management commands from it.
    """

    def _get_command(self):
        from config.management.commands.backup_db import Command
        cmd = Command()
        cmd.style = MagicMock()
        cmd.style.SUCCESS = lambda s: s
        cmd.style.ERROR = lambda s: s
        cmd.style.WARNING = lambda s: s
        cmd.stdout = io.StringIO()
        cmd.stderr = io.StringIO()
        return cmd

    def _run_command(self, cmd, options):
        """Call handle() and capture stdout/stderr, return (exit_code, stdout, stderr)."""
        try:
            cmd.handle(**options)
            return 0, cmd.stdout.getvalue(), cmd.stderr.getvalue()
        except SystemExit as e:
            return e.code, cmd.stdout.getvalue(), cmd.stderr.getvalue()

    def _default_options(self, **overrides):
        opts = {
            'keep': 7,
            'output': None,
            'verify': False,
            'restore_test': False,
        }
        opts.update(overrides)
        return opts

    def _real_sqlite_db(self):
        """Context manager: create a real SQLite file and mock settings.DATABASES to use it."""
        import sqlite3
        from unittest.mock import patch
        tmp = tempfile.NamedTemporaryFile(suffix='.sqlite3', delete=False)
        tmp_path = Path(tmp.name)
        tmp.close()
        # Create minimal valid SQLite DB
        conn = sqlite3.connect(str(tmp_path))
        conn.execute('CREATE TABLE IF NOT EXISTS _test (id INTEGER PRIMARY KEY)')
        conn.commit()
        conn.close()
        fake_dbs = {'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': tmp_path,
        }}
        return tmp_path, patch('config.management.commands.backup_db.settings.DATABASES', fake_dbs)

    def test_backup_sqlite_succeeds(self):
        """Backup should create a file and exit 0."""
        tmp_path, db_patch = self._real_sqlite_db()
        try:
            with db_patch, tempfile.TemporaryDirectory() as tmp_dir:
                cmd = self._get_command()
                exit_code, stdout, stderr = self._run_command(
                    cmd, self._default_options(output=tmp_dir, keep=1)
                )
                self.assertEqual(exit_code, 0, msg=f'stderr: {stderr}')
                backups = list(Path(tmp_dir).glob('backup_sqlite_*.sqlite3'))
                self.assertEqual(len(backups), 1)
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_backup_with_verify_passes(self):
        """--verify should pass for a valid backup."""
        tmp_path, db_patch = self._real_sqlite_db()
        try:
            with db_patch, tempfile.TemporaryDirectory() as tmp_dir:
                cmd = self._get_command()
                exit_code, stdout, stderr = self._run_command(
                    cmd, self._default_options(output=tmp_dir, keep=1, verify=True)
                )
                self.assertEqual(exit_code, 0, msg=f'stderr: {stderr}')
                self.assertIn('VERIFY OK', stdout)
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_backup_with_restore_test_passes(self):
        """--restore-test should pass for a valid SQLite backup."""
        tmp_path, db_patch = self._real_sqlite_db()
        try:
            with db_patch, tempfile.TemporaryDirectory() as tmp_dir:
                cmd = self._get_command()
                exit_code, stdout, stderr = self._run_command(
                    cmd, self._default_options(output=tmp_dir, keep=1, verify=True, restore_test=True)
                )
                self.assertEqual(exit_code, 0, msg=f'stderr: {stderr}')
                self.assertIn('RESTORE-TEST OK', stdout)
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_backup_rotation_keeps_correct_count(self):
        """backup --keep 2 should leave at most 2 backups after rotation."""
        import time
        tmp_path, db_patch = self._real_sqlite_db()
        try:
            with db_patch, tempfile.TemporaryDirectory() as tmp_dir:
                tmp_dir_path = Path(tmp_dir)
                # Pre-create 2 old backup files with distinct old timestamps
                for i in range(1, 3):
                    old_file = tmp_dir_path / f'backup_sqlite_20240101_00000{i}.sqlite3'
                    old_file.write_bytes(b'old backup data')
                    # Ensure mtime is distinct and in the past
                    mtime = 1000000 + i
                    os.utime(old_file, (mtime, mtime))

                # Now run a fresh backup with keep=2 — should rotate out the 2 oldest
                cmd = self._get_command()
                exit_code, _, stderr = self._run_command(
                    cmd, self._default_options(output=tmp_dir, keep=2)
                )
                self.assertEqual(exit_code, 0, msg=f'stderr: {stderr}')
                backups = list(tmp_dir_path.glob('backup_sqlite_*.sqlite3'))
                # There should be at most 2 backups (the 2 most recent)
                self.assertLessEqual(len(backups), 2)
                self.assertGreaterEqual(len(backups), 1)
        finally:
            tmp_path.unlink(missing_ok=True)


    def test_backup_with_invalid_encryption_key_exits_1(self):
        """An invalid BACKUP_ENCRYPTION_KEY should cause exit code 1."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.dict(os.environ, {'BACKUP_ENCRYPTION_KEY': 'not-a-valid-fernet-key'}):
                cmd = self._get_command()
                exit_code, _, stderr = self._run_command(
                    cmd, self._default_options(output=tmp_dir)
                )
            self.assertEqual(exit_code, 1)
            self.assertIn('Invalid BACKUP_ENCRYPTION_KEY', stderr)

    def test_backup_unsupported_engine_exits_1(self):
        """Unsupported DB engine should cause exit code 1."""
        from config.management.commands.backup_db import Command
        with patch('config.management.commands.backup_db.settings') as mock_settings:
            mock_settings.BASE_DIR = Path(tempfile.gettempdir())
            mock_settings.DATABASES = {
                'default': {'ENGINE': 'django.db.backends.oracle'}
            }
            cmd = Command()
            cmd.stdout = io.StringIO()
            cmd.stderr = io.StringIO()
            cmd.style = MagicMock()
            cmd.style.ERROR = lambda s: s
            cmd.style.WARNING = lambda s: s
            cmd.style.SUCCESS = lambda s: s
            try:
                cmd.handle(**self._default_options())
                exit_code = 0
            except SystemExit as e:
                exit_code = e.code
        self.assertEqual(exit_code, 1)
        self.assertIn('Unsupported', cmd.stderr.getvalue())

