# Production Deployment Checklist

Use this checklist before every production deployment. Mark each item ✅ when confirmed.

---

## 1. Django Core Settings

- [ ] `DEBUG=False` is set in production environment
- [ ] `SECRET_KEY` is set from environment variable — **never hardcoded**
- [ ] `ALLOWED_HOSTS` includes the production domain(s)
- [ ] `CSRF_TRUSTED_ORIGINS` includes all production origins with `https://`

---

## 2. Database

- [ ] PostgreSQL (or production DB) is configured via env vars, not SQLite
- [ ] `POSTGRES_PASSWORD` is a strong, randomly generated password
- [ ] DB connection is verified: `python manage.py dbshell` or health check
- [ ] All migrations are applied: `python manage.py migrate`
- [ ] Migration status verified: `GET /health/` shows `migrations: ok`

---

## 3. Static & Media Files

- [ ] `python manage.py collectstatic --no-input` has been run
- [ ] `STATIC_ROOT` directory is served by the web server (nginx/Apache)
- [ ] `MEDIA_ROOT` directory exists and is writable by the application user
- [ ] Media directory write access verified: `GET /health/` shows `media: ok`

---

## 4. HTTPS & Security Headers

- [ ] HTTPS is enabled and HTTP redirects to HTTPS
- [ ] `SECURE_SSL_REDIRECT=True`
- [ ] `SESSION_COOKIE_SECURE=True`
- [ ] `CSRF_COOKIE_SECURE=True`
- [ ] `SECURE_HSTS_SECONDS=31536000` (1 year minimum)
- [ ] `SECURE_HSTS_INCLUDE_SUBDOMAINS=True`
- [ ] SSL certificate is valid and not expiring within 30 days
- [ ] `X_FRAME_OPTIONS=DENY` (clickjacking protection)

---

## 5. Backup

- [ ] `BACKUP_ENCRYPTION_KEY` is set (generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`)
- [ ] Encryption key is stored securely (password manager / secrets manager) — **not in code**
- [ ] Backup runs successfully: `python manage.py backup_db`
- [ ] Backup verified: `python manage.py backup_db --verify`
- [ ] Restore tested: `python manage.py backup_db --restore-test` (SQLite) or manual restore procedure tested (PostgreSQL)
- [ ] Automated backup schedule configured (cron / Task Scheduler)
- [ ] Old backups are being rotated (`--keep` parameter set appropriately)
- [ ] Backup directory has sufficient disk space

### Off-site Backup (optional but recommended)

- [ ] `AWS_S3_BUCKET_NAME` configured (or left empty to skip)
- [ ] Off-site upload tested: `python manage.py backup_upload <backup_file>`
- [ ] Remote backup accessibility confirmed

---

## 6. Logging

- [ ] `LOG_DIR` is set and the directory is writable
- [ ] `logs/django.log` is being written (check after first request)
- [ ] `logs/security.log` is being written
- [ ] `logs/errors.log` is accessible
- [ ] Log rotation is configured (handled automatically by `RotatingFileHandler`)
- [ ] Log files are **not** publicly accessible via web server

---

## 7. Error Monitoring — Sentry (optional)

- [ ] `SENTRY_DSN` is set **or** left empty (application works either way)
- [ ] If set: `sentry-sdk` is installed (`pip install sentry-sdk`)
- [ ] If set: a test error has been triggered and appears in Sentry dashboard
- [ ] `send_default_pii=False` is confirmed in Sentry config
- [ ] `APP_VERSION` / release tag is set for deployment tracking

---

## 8. Admin & Access

- [ ] Django admin URL is secured (consider changing from default `/admin/`)
- [ ] All default/test passwords have been changed or removed
- [ ] All test user accounts have been removed or deactivated
- [ ] Superuser account uses a strong, unique password
- [ ] Admin access is restricted to trusted IPs if possible (nginx/firewall level)

---

## 9. Application Health

- [ ] Health check passes: `curl https://yourdomain.com/health/` returns `{"status": "ok"}`
- [ ] No 500 errors in error log after deployment
- [ ] Key user flows tested manually (login, sales order, invoice)

---

## 10. Infrastructure

- [ ] Firewall allows only ports 80 and 443 externally
- [ ] SSH access restricted to key-based authentication
- [ ] Database port (5432) is NOT publicly exposed
- [ ] Application runs as a non-root system user
- [ ] Process manager configured (systemd / Gunicorn supervisor)

---

## Sign-off

| Item | Verified By | Date |
|------|-------------|------|
| Pre-deployment checklist complete | | |
| Backup and restore tested | | |
| Security review complete | | |
| Health check passing | | |

---

> **Note:** This checklist should be reviewed and updated with each major release.
> Keep a signed copy in your deployment records.
