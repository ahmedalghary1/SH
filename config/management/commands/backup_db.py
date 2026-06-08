"""
backup_db management command
============================
Creates an encrypted (optional) database backup for SQLite or PostgreSQL.

Options:
  --keep N          Number of backups to keep (default: 7)
  --output DIR      Custom output directory (default: backups/)
  --verify          Verify the backup file was created and is readable
  --restore-test    Test restoring a SQLite backup to a temp file (SQLite only)

Encryption:
  Set BACKUP_ENCRYPTION_KEY env var to a 32-byte Fernet key (base64-encoded).
  Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  If the env var is absent, backups are stored unencrypted.

Exit codes:
  0 — success
  1 — backup failed
"""
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


def _get_fernet():
    """Return a Fernet instance from BACKUP_ENCRYPTION_KEY env var, or None."""
    key = os.environ.get('BACKUP_ENCRYPTION_KEY', '').strip()
    if not key:
        return None
    try:
        from cryptography.fernet import Fernet
        return Fernet(key.encode())
    except ImportError:
        raise RuntimeError(
            'cryptography package is required for encrypted backups. '
            'Install it with: pip install cryptography'
        )
    except Exception as exc:
        raise RuntimeError(
            f'Invalid BACKUP_ENCRYPTION_KEY: {exc}. '
            'Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )


class Command(BaseCommand):
    help = (
        'Create a backup of the database. Supports SQLite and PostgreSQL. '
        'Optionally encrypts the backup using BACKUP_ENCRYPTION_KEY env var.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--keep',
            type=int,
            default=7,
            help='Number of backups to keep (default: 7)',
        )
        parser.add_argument(
            '--output',
            type=str,
            default=None,
            help='Custom output directory (default: backups/)',
        )
        parser.add_argument(
            '--verify',
            action='store_true',
            help='Verify that the backup file was created and is readable after backup.',
        )
        parser.add_argument(
            '--restore-test',
            action='store_true',
            dest='restore_test',
            help='Test restoring the SQLite backup to a temporary file (SQLite only).',
        )

    def handle(self, *args, **options):
        keep_count = options['keep']
        output_dir = options['output'] or 'backups'
        do_verify = options['verify']
        do_restore_test = options['restore_test']

        # Create backup directory
        backup_dir = Path(settings.BASE_DIR) / output_dir
        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.stderr.write(self.style.ERROR(f'Cannot create backup directory {backup_dir}: {exc}'))
            sys.exit(1)

        # Determine engine
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        db_engine = settings.DATABASES['default']['ENGINE']

        try:
            fernet = _get_fernet()
        except RuntimeError as exc:
            self.stderr.write(self.style.ERROR(str(exc)))
            sys.exit(1)

        encrypted = fernet is not None
        enc_suffix = '.enc' if encrypted else ''

        if 'postgresql' in db_engine or 'postgres' in db_engine:
            raw_file = backup_dir / f'backup_postgres_{timestamp}.sql'
            backup_file = Path(str(raw_file) + enc_suffix)
            success = self._backup_postgresql(raw_file, fernet, backup_file)
        elif 'sqlite' in db_engine:
            raw_file = backup_dir / f'backup_sqlite_{timestamp}.sqlite3'
            backup_file = Path(str(raw_file) + enc_suffix)
            success = self._backup_sqlite(raw_file, fernet, backup_file)
        else:
            self.stderr.write(self.style.ERROR(f'Unsupported database engine: {db_engine}'))
            sys.exit(1)

        if not success:
            sys.exit(1)

        enc_note = ' (encrypted)' if encrypted else ''
        self.stdout.write(self.style.SUCCESS(f'Backup created: {backup_file}{enc_note}'))

        # Rotate old backups
        self._rotate_backups(backup_dir, keep_count, db_engine, encrypted)

        # --verify
        if do_verify:
            self._verify_backup(backup_file, fernet)

        # --restore-test (SQLite only)
        if do_restore_test:
            if 'sqlite' in db_engine:
                self._restore_test(backup_file, fernet)
            else:
                self.stdout.write(self.style.WARNING(
                    '--restore-test is only supported for SQLite databases.'
                ))

    # ------------------------------------------------------------------ #
    #  Backup methods                                                      #
    # ------------------------------------------------------------------ #

    def _backup_sqlite(self, raw_file, fernet, final_file):
        """Backup SQLite database by copying the file, then optionally encrypting."""
        db_name = settings.DATABASES['default']['NAME']
        db_path = Path(db_name) if not isinstance(db_name, Path) else db_name

        if not db_path.exists():
            self.stderr.write(self.style.ERROR(f'Database file not found: {db_path}'))
            return False

        try:
            shutil.copy2(db_path, raw_file)
        except OSError as exc:
            self.stderr.write(self.style.ERROR(f'Failed to copy SQLite file: {exc}'))
            return False

        if fernet:
            return self._encrypt_file(raw_file, final_file)
        return True

    def _backup_postgresql(self, raw_file, fernet, final_file):
        """Backup PostgreSQL using pg_dump, then optionally encrypt."""
        pg_dump = shutil.which('pg_dump')
        if not pg_dump:
            self.stderr.write(self.style.ERROR(
                'pg_dump not found. Install PostgreSQL client tools.'
            ))
            return False

        db_config = settings.DATABASES['default']
        env = os.environ.copy()
        env['PGPASSWORD'] = db_config.get('PASSWORD', '')

        cmd = [
            'pg_dump',
            '-h', db_config.get('HOST', 'localhost'),
            '-p', str(db_config.get('PORT', '5432')),
            '-U', db_config.get('USER', 'postgres'),
            '-d', db_config.get('NAME', ''),
            '-f', str(raw_file),
            '--no-owner',
            '--no-acl',
        ]

        try:
            result = subprocess.run(
                cmd, env=env, check=False, capture_output=True, text=True
            )
            if result.returncode != 0:
                self.stderr.write(self.style.ERROR(
                    f'pg_dump exited with code {result.returncode}: {result.stderr.strip()}'
                ))
                return False
        except FileNotFoundError:
            self.stderr.write(self.style.ERROR('pg_dump executable not found.'))
            return False
        except OSError as exc:
            self.stderr.write(self.style.ERROR(f'pg_dump failed: {exc}'))
            return False

        if fernet:
            return self._encrypt_file(raw_file, final_file)
        return True

    # ------------------------------------------------------------------ #
    #  Encryption helpers                                                  #
    # ------------------------------------------------------------------ #

    def _encrypt_file(self, source: Path, dest: Path) -> bool:
        """Encrypt source file to dest, then remove source."""
        try:
            from cryptography.fernet import Fernet  # noqa: F401 — already imported in _get_fernet
            data = source.read_bytes()
            # Re-fetch fernet from env (already validated earlier)
            key = os.environ.get('BACKUP_ENCRYPTION_KEY', '').strip().encode()
            from cryptography.fernet import Fernet
            fernet = Fernet(key)
            encrypted = fernet.encrypt(data)
            dest.write_bytes(encrypted)
            source.unlink()  # Remove plaintext
            return True
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f'Encryption failed: {exc}'))
            # Remove partial encrypted file if exists
            if dest.exists():
                dest.unlink(missing_ok=True)
            return False

    # ------------------------------------------------------------------ #
    #  Verify & Restore-test                                              #
    # ------------------------------------------------------------------ #

    def _verify_backup(self, backup_file: Path, fernet):
        """Verify that backup file exists and is readable."""
        if not backup_file.exists():
            self.stderr.write(self.style.ERROR(f'VERIFY FAILED: File not found: {backup_file}'))
            sys.exit(1)

        size = backup_file.stat().st_size
        if size == 0:
            self.stderr.write(self.style.ERROR(f'VERIFY FAILED: Backup file is empty: {backup_file}'))
            sys.exit(1)

        # If encrypted, try decrypting a small chunk to prove key works
        if fernet:
            try:
                data = backup_file.read_bytes()
                fernet.decrypt(data)
                self.stdout.write(self.style.SUCCESS(
                    f'VERIFY OK: {backup_file.name} ({size:,} bytes, decryption verified)'
                ))
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f'VERIFY FAILED: Cannot decrypt backup: {exc}'))
                sys.exit(1)
        else:
            self.stdout.write(self.style.SUCCESS(
                f'VERIFY OK: {backup_file.name} ({size:,} bytes)'
            ))

    def _restore_test(self, backup_file: Path, fernet):
        """Test restore: decrypt (if needed) and open the SQLite DB in a temp file."""
        self.stdout.write('Running restore test...')
        with tempfile.NamedTemporaryFile(suffix='.sqlite3', delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            if fernet:
                try:
                    data = backup_file.read_bytes()
                    plain = fernet.decrypt(data)
                    tmp_path.write_bytes(plain)
                except Exception as exc:
                    self.stderr.write(self.style.ERROR(f'RESTORE-TEST FAILED: Decryption error: {exc}'))
                    sys.exit(1)
            else:
                shutil.copy2(backup_file, tmp_path)

            # Open the SQLite file and run a basic integrity check
            try:
                conn = sqlite3.connect(str(tmp_path))
                cursor = conn.execute('PRAGMA integrity_check')
                result = cursor.fetchone()
                conn.close()
                if result and result[0] == 'ok':
                    self.stdout.write(self.style.SUCCESS(
                        f'RESTORE-TEST OK: SQLite integrity check passed on temp restore.'
                    ))
                else:
                    self.stderr.write(self.style.ERROR(
                        f'RESTORE-TEST FAILED: integrity_check returned: {result}'
                    ))
                    sys.exit(1)
            except sqlite3.DatabaseError as exc:
                self.stderr.write(self.style.ERROR(f'RESTORE-TEST FAILED: Cannot open restored DB: {exc}'))
                sys.exit(1)
        finally:
            tmp_path.unlink(missing_ok=True)

    # ------------------------------------------------------------------ #
    #  Rotation                                                            #
    # ------------------------------------------------------------------ #

    def _rotate_backups(self, backup_dir: Path, keep_count: int, db_engine: str, encrypted: bool):
        """Remove old backups, keeping only the most recent ones."""
        enc_suffix = '.enc' if encrypted else ''
        if 'postgresql' in db_engine or 'postgres' in db_engine:
            pattern = f'backup_postgres_*.sql{enc_suffix}'
        else:
            pattern = f'backup_sqlite_*.sqlite3{enc_suffix}'

        backups = sorted(
            backup_dir.glob(pattern),
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        )
        for old_backup in backups[keep_count:]:
            old_backup.unlink()
            self.stdout.write(self.style.WARNING(f'Removed old backup: {old_backup.name}'))
