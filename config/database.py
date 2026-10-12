"""Database configuration shared by deployments and local development."""

from pathlib import Path

from django.core.exceptions import ImproperlyConfigured


def database_config(environ, base_dir):
    def value(*names, default=''):
        return next((environ[name].strip() for name in names if environ.get(name, '').strip()), default)

    engine = value('DB_ENGINE', 'ENGINE').lower()
    if not engine:
        engine = 'postgres' if value('POSTGRES_DB', 'NAME') else 'sqlite'
    if engine in {'sqlite', 'sqlite3', 'django.db.backends.sqlite3'}:
        name = value('SQLITE_PATH', 'DB_NAME', default=str(Path(base_dir) / 'db.sqlite3'))
        return {'ENGINE': 'django.db.backends.sqlite3', 'NAME': name, 'OPTIONS': {'timeout': 20}}
    if engine not in {'postgres', 'postgresql', 'django.db.backends.postgresql', 'django.db.backends.postgresql_psycopg2'}:
        raise ImproperlyConfigured('DB_ENGINE must select PostgreSQL or SQLite.')
    name = value('POSTGRES_DB', 'DB_NAME', 'NAME')
    user = value('POSTGRES_USER', 'DB_USER', 'USER')
    if not name or not user:
        raise ImproperlyConfigured('Set POSTGRES_DB and POSTGRES_USER for PostgreSQL (legacy NAME and USER are also accepted).')
    options = {'connect_timeout': int(value('DB_CONNECT_TIMEOUT', default='10'))}
    sslmode = value('POSTGRES_SSLMODE')
    if sslmode:
        options['sslmode'] = sslmode
    return {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': name,
        'USER': user,
        'PASSWORD': value('POSTGRES_PASSWORD', 'DB_PASSWORD', 'PASSWORD'),
        'HOST': value('POSTGRES_HOST', 'DB_HOST', 'HOST', default='localhost'),
        'PORT': value('POSTGRES_PORT', 'DB_PORT', 'PORT', default='5432'),
        'CONN_MAX_AGE': int(value('DB_CONN_MAX_AGE', default='60')),
        'CONN_HEALTH_CHECKS': value('DB_CONN_HEALTH_CHECKS', default='True').lower() in {'1', 'true', 'yes', 'on'},
        'OPTIONS': options,
    }
