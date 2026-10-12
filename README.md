# SH ERP

Django ERP for clothing sales, inventory, finance, purchases, returns, sales representatives, CRM, reports, and invoices.

## Local Setup

1. Create and activate a virtual environment.
2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Create a local `.env` from `.env.example` and set at least:

```text
SECRET_KEY=local-development-key
DEBUG=True
ALLOWED_HOSTS=127.0.0.1,localhost
```

4. Run database migrations:

```powershell
python manage.py migrate
```

5. Create an admin user:

```powershell
python manage.py createsuperuser
```

6. Start the development server:

```powershell
python manage.py runserver
```

## Tests And Checks

```powershell
python manage.py test
python manage.py check
python manage.py makemigrations --check --dry-run
```

## Static Files

For production, collect static files into `STATIC_ROOT`:

```powershell
python manage.py collectstatic
```

`STATIC_URL`, `STATIC_ROOT`, `MEDIA_URL`, and `MEDIA_ROOT` can be set in `.env`. Local development keeps SQLite by default and continues to serve media through Django URL configuration.

## PostgreSQL Production Example

Set these environment variables when deploying with PostgreSQL:

```text
DEBUG=False
ALLOWED_HOSTS=example.com,www.example.com
CSRF_TRUSTED_ORIGINS=https://example.com,https://www.example.com
DB_ENGINE=postgres
POSTGRES_DB=sh_erp
POSTGRES_USER=sh_erp
POSTGRES_PASSWORD=change-this-password
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

Do not commit real `.env` files, secrets, uploaded media, logs, or local SQLite databases.

The PostgreSQL values must identify the existing production database. Preserve
the server's private `.env`; do not replace it with the SQLite example. Legacy
`ENGINE`, `NAME`, `USER`, `PASSWORD`, `HOST`, and `PORT` are still accepted.
`DB_ENGINE` takes precedence if both formats exist. No database credentials are
embedded in the application. Connection health checks and a connection timeout
are enabled for PostgreSQL.

This release uses Django 5.2 LTS and requires Python 3.10 or newer. See the
[official supported versions](https://www.djangoproject.com/download/).

## Invoice Deletion

Managers with deletion permission can open the invoice's deletion confirmation
and POST its cancellation. The transaction restores stock to its original
warehouses, reverses actual payments in their original cash accounts, and removes
the remaining customer debt. Invoice, payment, and audit records are retained;
cancelled invoices disappear from the active list. Linked returns or handed-over
representative collections must be reconciled before deletion. Repeated deletion
does not reverse stock or cash twice. Editing/deletion requires a connection.

## Release Review And Offline Use

See [the Arabic review and deployment instructions](docs/review-2026-10-12-ar.md)
and [PWA behavior and limitations](docs/pwa_offline_sync.md). This release adds no
database schema migrations. Back up the production database and media, preserve
the private environment, collect static files, and restart the application when
deploying. A request reference is included on error pages and in application logs.
