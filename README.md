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
