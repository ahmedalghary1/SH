
import importlib.util
import os
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


def load_dotenv(path):
    if not path.exists():
        return
    for raw_line in path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def env_int(name, default):
    value = os.environ.get(name)
    if value is None or str(value).strip() == '':
        return default
    return int(value)


def env_list(name, default=''):
    value = os.environ.get(name)
    if not value:
        value = default
    return [item.strip() for item in value.split(',') if item.strip()]


def csrf_origins_from_hosts(hosts):
    origins = []
    for host in hosts:
        if not host or host == '*' or host.startswith('.'):
            continue
        if host in {'localhost', '127.0.0.1'}:
            origins.extend([f'http://{host}', f'https://{host}'])
        else:
            origins.append(f'https://{host}')
    return origins


def env_url(name, default):
    value = os.environ.get(name, default)
    if not value:
        value = default
    value = value.strip()
    if not value.startswith('/'):
        value = '/' + value
    if not value.endswith('/'):
        value = value + '/'
    return value


def env_path(name, default):
    value = os.environ.get(name)
    if not value:
        return Path(default)
    return Path(value).expanduser()


def env_paths(name):
    value = os.environ.get(name, '')
    paths = []
    for item in value.split(','):
        item = item.strip()
        if not item:
            continue
        path = Path(item).expanduser()
        paths.append(path if path.is_absolute() else BASE_DIR / path)
    return paths


load_dotenv(BASE_DIR / '.env')


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret.
SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-local-development-key-change-me')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env_bool('DEBUG', False)

ALLOWED_HOSTS = env_list(
    'ALLOWED_HOSTS',
    'sh.elwsamstore.com,www.sh.elwsamstore.com,localhost,127.0.0.1',
)
CSRF_TRUSTED_ORIGINS = env_list(
    'CSRF_TRUSTED_ORIGINS',
    ','.join(csrf_origins_from_hosts(ALLOWED_HOSTS)),
)
USE_WHITENOISE = (
    env_bool('USE_WHITENOISE', not DEBUG)
    and importlib.util.find_spec('whitenoise') is not None
)
# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'accounts',
    'products',
    'inventory',
    'customers',
    'orders',
    'invoices',
    'finance',
    'purchases',
    'returns',
    'sales_reps',
    'reports',
    'dashboard',
    'settings_app',
    'sync_api',
    'audit.apps.AuditConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
]
if USE_WHITENOISE:
    MIDDLEWARE.append('whitenoise.middleware.WhiteNoiseMiddleware')
MIDDLEWARE += [
    'sync_api.middleware.SyncApiCorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'accounts.middleware.BranchContextMiddleware',
    'accounts.middleware.DuplicateSubmissionMiddleware',
    'audit.middleware.AuditRequestMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'accounts.context_processors.branch_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'




DATABASES = {
    'default': {
        'ENGINE': os.environ.get('DB_ENGINE', 'django.db.backends.postgresql'),
        'NAME': os.environ.get('POSTGRES_DB', 'elwsamst_sh'),
        'USER': os.environ.get('POSTGRES_USER', 'elwsamst_system'),
        'PASSWORD': os.environ.get('POSTGRES_PASSWORD', 'ahmed01552810113'),
        'HOST': os.environ.get('POSTGRES_HOST', 'localhost'),
        'PORT': os.environ.get('POSTGRES_PORT', '5432'),
        'CONN_MAX_AGE': env_int('DB_CONN_MAX_AGE', 60),
    }
}

# Password validation
# https://docs.djangoproject.com/en/5.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.0/topics/i18n/

LANGUAGE_CODE = 'ar'

TIME_ZONE = 'Africa/Cairo'

USE_I18N = True

USE_TZ = True


# Static and media files
# On cPanel/Passenger, uploaded media stays outside the project code so
# deployments and git pulls do not remove user files. Static files can be
# served by Apache from STATIC_ROOT or by WhiteNoise from the Django app.
DEFAULT_PUBLIC_ROOT = BASE_DIR / 'public' if DEBUG else Path('/home/elwsamst/public_html')
PUBLIC_ROOT = env_path(
    'PUBLIC_ROOT',
    DEFAULT_PUBLIC_ROOT,
)

STATIC_URL = env_url('STATIC_URL', 'static/')
STATIC_ROOT = env_path('STATIC_ROOT', PUBLIC_ROOT / 'static')

STATIC_SOURCE_DIR = BASE_DIR / 'static'
STATICFILES_DIRS = []
if STATIC_SOURCE_DIR.exists() and STATIC_SOURCE_DIR.resolve() != STATIC_ROOT.resolve():
    STATICFILES_DIRS.append(STATIC_SOURCE_DIR)
WHITENOISE_USE_FINDERS = env_bool('WHITENOISE_USE_FINDERS', USE_WHITENOISE)
SERVE_STATIC_WITH_DJANGO = env_bool('SERVE_STATIC_WITH_DJANGO', not DEBUG)

DEFAULT_MEDIA_URL = 'media/' if DEBUG else 'sh_media/'
DEFAULT_MEDIA_ROOT = BASE_DIR / 'media' if DEBUG else PUBLIC_ROOT / 'sh_media'
MEDIA_URL = env_url('MEDIA_URL', DEFAULT_MEDIA_URL)
MEDIA_ROOT = env_path('MEDIA_ROOT', DEFAULT_MEDIA_ROOT)
SERVE_MEDIA_WITH_DJANGO = env_bool('SERVE_MEDIA_WITH_DJANGO', not DEBUG)
MEDIA_FALLBACK_ROOTS = env_paths('MEDIA_FALLBACK_ROOTS')
for media_fallback_root in (BASE_DIR / 'media', PUBLIC_ROOT / 'media'):
    if media_fallback_root.resolve() != MEDIA_ROOT.resolve() and media_fallback_root not in MEDIA_FALLBACK_ROOTS:
        MEDIA_FALLBACK_ROOTS.append(media_fallback_root)

AUTH_USER_MODEL = 'accounts.User'
LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'dashboard:index'
LOGOUT_REDIRECT_URL = 'accounts:login'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

SESSION_ENGINE = os.environ.get('SESSION_ENGINE', 'django.contrib.sessions.backends.db')
SESSION_COOKIE_NAME = os.environ.get('SESSION_COOKIE_NAME', 'sessionid')
SESSION_COOKIE_AGE = env_int('SESSION_COOKIE_AGE', 60 * 60 * 24 * 30)
SESSION_SAVE_EVERY_REQUEST = env_bool('SESSION_SAVE_EVERY_REQUEST', True)
SESSION_EXPIRE_AT_BROWSER_CLOSE = env_bool('SESSION_EXPIRE_AT_BROWSER_CLOSE', False)
SESSION_COOKIE_HTTPONLY = env_bool('SESSION_COOKIE_HTTPONLY', True)
SESSION_COOKIE_SECURE = env_bool('SESSION_COOKIE_SECURE', False)
CSRF_COOKIE_SECURE = env_bool('CSRF_COOKIE_SECURE', False)
CSRF_COOKIE_HTTPONLY = env_bool('CSRF_COOKIE_HTTPONLY', False)
SESSION_COOKIE_SAMESITE = os.environ.get('SESSION_COOKIE_SAMESITE', 'Lax')
CSRF_COOKIE_SAMESITE = os.environ.get('CSRF_COOKIE_SAMESITE', 'Lax')
SESSION_COOKIE_DOMAIN = os.environ.get('SESSION_COOKIE_DOMAIN') or None
CSRF_COOKIE_DOMAIN = os.environ.get('CSRF_COOKIE_DOMAIN') or None
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = env_bool('SECURE_SSL_REDIRECT', False)
SECURE_HSTS_SECONDS = int(os.environ.get('SECURE_HSTS_SECONDS', '0'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool('SECURE_HSTS_INCLUDE_SUBDOMAINS', False)
SECURE_HSTS_PRELOAD = env_bool('SECURE_HSTS_PRELOAD', False)
SECURE_CONTENT_TYPE_NOSNIFF = env_bool('SECURE_CONTENT_TYPE_NOSNIFF', True)
SECURE_REFERRER_POLICY = os.environ.get('SECURE_REFERRER_POLICY', 'same-origin')
X_FRAME_OPTIONS = os.environ.get('X_FRAME_OPTIONS', 'DENY')

PDF_ARABIC_FONT_PATH = os.environ.get('PDF_ARABIC_FONT_PATH', '').strip()



LOG_DIR = Path(os.environ.get('LOG_DIR', BASE_DIR / 'logs'))
LOG_DIR.mkdir(exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {name} {module} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {asctime} {message}',
            'style': '{',
        },
    },
    'filters': {
        'sanitize': {
            '()': 'config.log_sanitizer.SanitizingFilter',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
            'filters': ['sanitize'],
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': os.environ.get('LOG_LEVEL', 'INFO'),
            'propagate': False,
        },
        'business': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'security': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
    },
    'root': {
        'handlers': ['console'],
        'level': os.environ.get('LOG_LEVEL', 'INFO'),
    },
}

if not DEBUG:
    LOGGING['handlers']['django_file'] = {
        'class': 'logging.handlers.RotatingFileHandler',
        'filename': LOG_DIR / 'django.log',
        'maxBytes': 1024 * 1024 * 10,
        'backupCount': 10,
        'formatter': 'verbose',
        'filters': ['sanitize'],
    }
    LOGGING['handlers']['error_file'] = {
        'class': 'logging.handlers.RotatingFileHandler',
        'filename': LOG_DIR / 'errors.log',
        'maxBytes': 1024 * 1024 * 10,
        'backupCount': 10,
        'formatter': 'verbose',
        'level': 'ERROR',
        'filters': ['sanitize'],
    }
    LOGGING['handlers']['business_file'] = {
        'class': 'logging.handlers.RotatingFileHandler',
        'filename': LOG_DIR / 'business.log',
        'maxBytes': 1024 * 1024 * 10,
        'backupCount': 10,
        'formatter': 'simple',
        'filters': ['sanitize'],
    }
    LOGGING['handlers']['security_file'] = {
        'class': 'logging.handlers.RotatingFileHandler',
        'filename': LOG_DIR / 'security.log',
        'maxBytes': 1024 * 1024 * 5,
        'backupCount': 30,  # Keep more security log rotations
        'formatter': 'verbose',
        'filters': ['sanitize'],
    }
    LOGGING['loggers']['django']['handlers'].append('django_file')
    LOGGING['loggers']['django']['handlers'].append('error_file')
    LOGGING['loggers']['business']['handlers'].append('business_file')
    LOGGING['loggers']['security']['handlers'].append('security_file')
    LOGGING['root']['handlers'].append('django_file')


# ------------------------------------------------------------------ #
#  Optional Sentry integration                                        #
#  Set SENTRY_DSN env var to enable. No error if sentry_sdk absent.  #
# ------------------------------------------------------------------ #
_SENTRY_DSN = os.environ.get('SENTRY_DSN', '').strip()
if _SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.django import DjangoIntegration
        from config.log_sanitizer import sanitize as _sanitize_log

        _SENTRY_SAMPLE_RATE = float(os.environ.get('SENTRY_TRACES_SAMPLE_RATE', '0.1'))

        def _sentry_before_send(event, hint):
            """Strip sensitive data before sending events to Sentry."""
            # Sanitize request data
            request_data = event.get('request', {})
            if 'data' in request_data:
                request_data['data'] = _sanitize_log(request_data['data'])
            if 'cookies' in request_data:
                request_data['cookies'] = '***REDACTED***'
            if 'headers' in request_data:
                headers = request_data['headers']
                for sensitive in ('Authorization', 'Cookie', 'X-Api-Key'):
                    if sensitive in headers:
                        headers[sensitive] = '***REDACTED***'
            # Sanitize extra context
            if 'extra' in event:
                event['extra'] = _sanitize_log(event['extra'])
            return event

        sentry_sdk.init(
            dsn=_SENTRY_DSN,
            integrations=[DjangoIntegration()],
            traces_sample_rate=_SENTRY_SAMPLE_RATE,
            send_default_pii=False,  # Never send PII
            before_send=_sentry_before_send,
            environment='production' if not DEBUG else 'development',
            release=os.environ.get('APP_VERSION', 'unknown'),
        )
    except ImportError:
        pass  # sentry_sdk not installed — silently skip
