import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'

# cPanel/Passenger entry point. Force production-safe defaults before Django
# reads .env so a copied development .env cannot leave login/CSRF broken.
os.environ['DEBUG'] = 'False'
os.environ['ALLOWED_HOSTS'] = 'sh.elwsamstore.com,www.sh.elwsamstore.com'
os.environ['CSRF_TRUSTED_ORIGINS'] = 'https://sh.elwsamstore.com,https://www.sh.elwsamstore.com'
os.environ['SESSION_COOKIE_SECURE'] = 'True'
os.environ['CSRF_COOKIE_SECURE'] = 'True'

from config.wsgi import application
