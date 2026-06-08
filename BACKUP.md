# Database Backup Guide

Complete guide for creating, encrypting, verifying, restoring, and automating database backups for the SH ERP system.

---

## Quick Start

```bash
# Create a backup (unencrypted)
python manage.py backup_db

# Create an encrypted backup (recommended for production)
BACKUP_ENCRYPTION_KEY=<your-key> python manage.py backup_db

# Create, then verify
python manage.py backup_db --verify

# Create, verify, and test restore (SQLite only)
python manage.py backup_db --verify --restore-test
```

---

## Backup Encryption

### Why Encrypt?

Backup files contain all your business data. Encrypting them protects against unauthorized access if the backup file is exposed.

### Generating an Encryption Key

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

This prints a base64-encoded 32-byte Fernet key. **Store it securely** — without it you cannot decrypt your backups.

**Requirements:**
```bash
pip install cryptography
```

### Setting the Key

Set `BACKUP_ENCRYPTION_KEY` as an environment variable. **Never put it in the code or commit it to git.**

```bash
# Linux/macOS
export BACKUP_ENCRYPTION_KEY="your-key-here"
python manage.py backup_db

# Windows PowerShell
$env:BACKUP_ENCRYPTION_KEY="your-key-here"
python manage.py backup_db
```

Or add it to your `.env` file (which must be in `.gitignore`):
```
BACKUP_ENCRYPTION_KEY=your-key-here
```

### Encrypted File Names

Encrypted backups have the `.enc` suffix:
- `backup_sqlite_20240101_020000.sqlite3.enc`
- `backup_postgres_20240101_020000.sql.enc`

---

## Backup Options

| Option | Description | Default |
|--------|-------------|---------|
| `--keep N` | Number of backups to retain | 7 |
| `--output DIR` | Custom output directory | `backups/` |
| `--verify` | Verify file was created and is readable/decryptable | off |
| `--restore-test` | Test SQLite restore to a temp file (SQLite only) | off |

### Examples

```bash
# Keep 30 days of backups in a custom directory
python manage.py backup_db --keep 30 --output /var/backups/sh_erp

# Backup, keep 14, verify integrity
python manage.py backup_db --keep 14 --verify

# Full test: backup + verify + restore test
python manage.py backup_db --verify --restore-test
```

---

## Verifying a Backup (`--verify`)

The `--verify` flag checks that:
1. The backup file was created and is not empty.
2. If encrypted: the file can be decrypted with the current `BACKUP_ENCRYPTION_KEY`.

```bash
python manage.py backup_db --verify
# Output:
# Backup created: backups/backup_sqlite_20240101_020000.sqlite3.enc (encrypted)
# VERIFY OK: backup_sqlite_20240101_020000.sqlite3.enc (245,760 bytes, decryption verified)
```

If verify fails, the command exits with **exit code 1**.

---

## Testing Restore (`--restore-test`)

The `--restore-test` flag (SQLite only):
1. Decrypts the backup (if encrypted).
2. Copies it to a temporary file.
3. Runs SQLite `PRAGMA integrity_check` on the copy.
4. Deletes the temporary file.

```bash
python manage.py backup_db --verify --restore-test
# Output:
# Backup created: backups/backup_sqlite_20240101_020000.sqlite3.enc (encrypted)
# VERIFY OK: backup_sqlite_20240101_020000.sqlite3.enc (245,760 bytes, decryption verified)
# Running restore test...
# RESTORE-TEST OK: SQLite integrity check passed on temp restore.
```

> **For PostgreSQL**: test restore manually on a staging database (see Manual Restore section below).

---

## Off-site Backup Upload (Optional)

Upload a backup file to S3-compatible storage:

```bash
python manage.py backup_upload backups/backup_sqlite_20240101_020000.sqlite3.enc
```

### Required Environment Variables

| Variable | Description |
|----------|-------------|
| `AWS_S3_BUCKET_NAME` | Bucket name (required to enable upload) |
| `AWS_ACCESS_KEY_ID` | Access key |
| `AWS_SECRET_ACCESS_KEY` | Secret key |
| `AWS_S3_ENDPOINT_URL` | Custom endpoint for non-AWS S3 (e.g. Cloudflare R2, MinIO) |
| `AWS_S3_REGION` | Region (default: `us-east-1`) |
| `AWS_S3_PREFIX` | Folder prefix in bucket (default: `backups/`) |

If `AWS_S3_BUCKET_NAME` is not set, the command prints a warning and exits 0 (no error).

**Requirements:**
```bash
pip install boto3
```

### Dry Run

```bash
python manage.py backup_upload backups/my_backup.sqlite3.enc --dry-run
# [DRY RUN] Would upload ... → s3://my-bucket/backups/my_backup.sqlite3.enc
```

### Combined: Backup + Upload

```bash
python manage.py backup_db --verify && \
python manage.py backup_upload backups/$(ls -t backups/ | head -1)
```

---

## Automated Backup

### Linux/macOS (cron)

Edit crontab (`crontab -e`):

```bash
# Daily backup at 2 AM — encrypt, keep 30, verify
0 2 * * * cd /path/to/project && source venv/bin/activate && python manage.py backup_db --keep 30 --verify >> /var/log/sh_backup.log 2>&1

# Upload to S3 at 2:30 AM
30 2 * * * cd /path/to/project && source venv/bin/activate && python manage.py backup_upload backups/$(ls -t backups/*.enc 2>/dev/null | head -1) >> /var/log/sh_backup.log 2>&1
```

### Windows (Task Scheduler)

Create a `.bat` file:
```batch
@echo off
cd C:\path\to\project
call venv\Scripts\activate
python manage.py backup_db --keep 30 --verify
python manage.py backup_upload backups\
```

Schedule it to run daily via Task Scheduler.

---

## Manual Restore

### SQLite

1. Stop the application.
2. Replace the database file:
   ```bash
   # Unencrypted backup
   copy backups\backup_sqlite_YYYYMMDD_HHMMSS.sqlite3 db.sqlite3

   # Encrypted backup — decrypt first using Python:
   python -c "
   from cryptography.fernet import Fernet
   import os
   key = os.environ['BACKUP_ENCRYPTION_KEY'].encode()
   f = Fernet(key)
   data = open('backups/backup_sqlite_YYYYMMDD_HHMMSS.sqlite3.enc', 'rb').read()
   open('db.sqlite3', 'wb').write(f.decrypt(data))
   print('Decrypted successfully')
   "
   ```
3. Restart the application.

### PostgreSQL

```bash
# Unencrypted
psql -h localhost -U sh_erp_user -d sh_erp < backups/backup_postgres_YYYYMMDD_HHMMSS.sql

# Encrypted — decrypt first
python -c "
from cryptography.fernet import Fernet
import os
key = os.environ['BACKUP_ENCRYPTION_KEY'].encode()
f = Fernet(key)
data = open('backups/backup_postgres_YYYYMMDD_HHMMSS.sql.enc', 'rb').read()
open('/tmp/restore.sql', 'wb').write(f.decrypt(data))
print('Decrypted to /tmp/restore.sql')
"
psql -h localhost -U sh_erp_user -d sh_erp < /tmp/restore.sql
rm /tmp/restore.sql
```

---

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | Backup failed, verify failed, or restore-test failed |

Scripts can check `$?` (Linux) or `%ERRORLEVEL%` (Windows) to detect failures.

---

## Important Notes

- Backup files are **not committed to git** (see `.gitignore`)
- The `BACKUP_ENCRYPTION_KEY` must be stored securely — losing it means losing your backups
- Test the restore procedure **before** a disaster occurs
- Monitor disk space in the backup directory
- Consider off-site storage for disaster recovery
