import os
import threading
import time

from .services import sync_once


_worker_started = False


def _loop(interval):
    while True:
        try:
            sync_once()
        except Exception:
            pass
        time.sleep(interval)


def start_worker():
    global _worker_started
    if _worker_started:
        return
    _worker_started = True
    interval = int(os.environ.get('DESKTOP_SYNC_INTERVAL_SECONDS', '60'))
    thread = threading.Thread(target=_loop, args=(interval,), daemon=True, name='desktop-sync-worker')
    thread.start()
