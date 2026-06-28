from contextlib import contextmanager
from contextvars import ContextVar


_sync_importing = ContextVar('desktop_sync_importing', default=False)


def is_importing():
    return _sync_importing.get()


@contextmanager
def importing_from_server():
    token = _sync_importing.set(True)
    try:
        yield
    finally:
        _sync_importing.reset(token)
