import argparse
import os
import socket
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR
APP_NAME = "SHDesktop"


def default_data_dir():
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if appdata:
            return Path(appdata) / APP_NAME

    return Path.home() / f".{APP_NAME.lower()}"


def configure_django():
    sys.path.insert(0, str(BACKEND_DIR))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    os.environ.setdefault("DESKTOP_LOCAL_MODE", "1")
    os.environ.setdefault("DEBUG", "0")
    os.environ.setdefault("DJANGO_DATA_DIR", str(default_data_dir()))
    os.environ.setdefault("DB_ENGINE", "django.db.backends.sqlite3")
    os.environ.setdefault("POSTGRES_DB", str(default_data_dir() / "db.sqlite3"))
    os.environ.setdefault("PUBLIC_ROOT", str(default_data_dir() / "public"))
    os.environ.setdefault("MEDIA_ROOT", str(default_data_dir() / "media"))
    os.environ.setdefault("STATIC_ROOT", str(default_data_dir() / "staticfiles"))
    os.environ.setdefault("LOG_DIR", str(default_data_dir() / "logs"))
    os.environ.setdefault("SERVE_STATIC_WITH_DJANGO", "1")
    os.environ.setdefault("SERVE_MEDIA_WITH_DJANGO", "1")
    os.environ.setdefault("SECURE_SSL_REDIRECT", "0")
    os.environ.setdefault("SESSION_COOKIE_SECURE", "0")
    os.environ.setdefault("CSRF_COOKIE_SECURE", "0")
    os.environ.setdefault("ALLOWED_HOSTS", "127.0.0.1,localhost")
    os.environ.setdefault("CSRF_TRUSTED_ORIGINS", "http://127.0.0.1,http://localhost")

    import django

    django.setup()


def parse_args():
    parser = argparse.ArgumentParser(description="Start the Clothing Store desktop backend.")
    parser.add_argument(
        "--host",
        default=os.getenv("APP_HOST", "127.0.0.1"),
        help="The host interface for the local desktop server.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("APP_PORT", "8000")),
        help="The port for the local desktop server.",
    )
    return parser.parse_args()


def get_lan_addresses():
    addresses = set()

    try:
        addresses.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe_socket:
            probe_socket.connect(("8.8.8.8", 80))
            addresses.add(probe_socket.getsockname()[0])
    except OSError:
        pass

    return sorted(address for address in addresses if address and not address.startswith("127."))


def print_server_urls(host, port):
    print(f"Starting backend on http://{host}:{port} ...")
    print(f"Local URL: http://127.0.0.1:{port}/")

    if host in {"0.0.0.0", "::"}:
        for address in get_lan_addresses():
            print(f"Network URL: http://{address}:{port}/")


def ensure_database_is_ready():
    from django.conf import settings
    from django.core.management import call_command
    from django.db import connections
    from django.db.migrations.executor import MigrationExecutor

    db_path = Path(settings.DATABASES["default"]["NAME"])
    db_path.parent.mkdir(parents=True, exist_ok=True)
    Path(settings.MEDIA_ROOT).mkdir(parents=True, exist_ok=True)

    print(f"Using database: {db_path}")
    call_command("migrate", "--noinput", verbosity=0)

    connection = connections["default"]
    executor = MigrationExecutor(connection)
    targets = executor.loader.graph.leaf_nodes()
    if executor.migration_plan(targets):
        call_command("migrate", "--noinput", verbosity=0)

    call_command("collectstatic", "--noinput", verbosity=0)


def start_desktop_sync_worker():
    if os.environ.get("DESKTOP_SYNC_AUTOSTART", "1").strip().lower() in {"0", "false", "no"}:
        return
    try:
        from desktop_sync.worker import start_worker

        start_worker()
    except Exception as exc:
        print(f"Desktop sync worker did not start: {exc}")


def main():
    args = parse_args()
    configure_django()
    ensure_database_is_ready()
    start_desktop_sync_worker()

    from config.wsgi import application
    from waitress import serve

    print_server_urls(args.host, args.port)
    serve(application, host=args.host, port=args.port, threads=6)


if __name__ == "__main__":
    main()
