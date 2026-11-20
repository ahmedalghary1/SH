"""Real Chromium installability, concurrent identity and cold offline storage.

Uses an isolated browser profile and a local HTTP fixture, never business data.
Run: .venv-audit/Scripts/python.exe tests/pwa_lifecycle_browser_review.py
"""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
unavailable = threading.Event()


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        path = urlsplit(self.path).path
        if unavailable.is_set():
            self.send_error(503)
            return
        if path == '/service-worker.js':
            self.path = '/static/service-worker.js'
            super().do_GET()
            return
        if path == '/manifest.json':
            manifest = json.loads((ROOT / 'static/manifest.json').read_text(encoding='utf-8'))
            origin = f'http://127.0.0.1:{self.server.server_port}'
            manifest['related_applications'] = [{'platform': 'webapp', 'id': origin + '/', 'url': origin + '/manifest.json'}]
            content = json.dumps(manifest).encode()
            content_type = 'application/manifest+json'
        elif path in {'/', '/invoices/', '/accounts/users/', '/offline/'}:
            content = b'''<!doctype html><html lang="ar"><head><meta name="viewport" content="width=device-width"><link rel="manifest" href="/manifest.json"><title>SH lifecycle</title></head>
<body data-pwa-user-id="1" data-pwa-branch-id="1" data-pwa-role="manager" data-pwa-superuser="0"><section data-page-content>SH</section><button data-pwa-install hidden>Install</button><script src="/static/js/pwa/install.js"></script></body></html>'''
            content_type = 'text/html; charset=utf-8'
        else:
            super().do_GET()
            return
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(content)))
        if path in {'/', '/invoices/', '/accounts/users/'}:
            self.send_header('X-PWA-Scope', 'u1-b1-rmanager-s0')
        if path in {'/', '/invoices/'}:
            self.send_header('X-PWA-Cacheable', '1')
            self.send_header('Cache-Control', 'private, no-cache')
        self.end_headers()
        self.wfile.write(content)


def main():
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(ROOT)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with tempfile.TemporaryDirectory(prefix='sh-pwa-lifecycle-') as profile, sync_playwright() as pw:
            browser_options = {'executable_path': os.environ['PWA_BROWSER_EXECUTABLE']} if os.environ.get('PWA_BROWSER_EXECUTABLE') else {}
            context = pw.chromium.launch_persistent_context(profile, headless=True, **browser_options)
            try:
                page = context.pages[0]
                page.goto(base)
                page.evaluate("async () => {await navigator.serviceWorker.register('/service-worker.js'); await navigator.serviceWorker.ready;}")
                page.wait_for_function('!!navigator.serviceWorker.controller')
                page.reload()
                cdp = context.new_cdp_session(page)
                result = cdp.send('Page.getInstallabilityErrors')
                assert not result['installabilityErrors'], result
                print('PASS: Chromium reports no PWA installability errors', flush=True)
                other = context.new_page()
                other.goto(base)
                for tab in [page, other]:
                    tab.evaluate("async () => {window.db=await import('/static/js/pwa/db.js');}")
                page.evaluate("db.deleteRecord(db.STORE_NAMES.metadata, 'device_id')")
                # Concurrent first use in separate JS realms against one IndexedDB.
                ids = []
                page.evaluate('window.ids=Promise.all(Array.from({length:24},()=>db.getDeviceId()))')
                other.evaluate('window.ids=Promise.all(Array.from({length:24},()=>db.getDeviceId()))')
                for tab in [page, other]:
                    ids.extend(tab.evaluate('window.ids'))
                assert len(set(ids)) == 1, ids
                operation = page.evaluate("""async () => {
                    const database=await db.openOfflineDB();
                    const original=database.transaction.bind(database);
                    let durability;
                    database.transaction=(...args)=>{
                        const tx=original(...args);
                        if(args[1]==='readwrite' && Array.isArray(args[0]) && args[0].includes('sync_queue')) durability=tx.durability;
                        return tx;
                    };
                    const item=await db.queueEntityOperation('customers','create',{customer:{name:'Cold restart customer'}});
                    return {key:item.idempotency_key,id:item.id,device:await db.getDeviceId(),durability};
                }""")
                assert operation['durability'] == 'strict', operation
                print('PASS: simultaneous first use keeps one device ID across tabs', flush=True)
                page.goto(base + '/invoices/')
                page.goto(base + '/accounts/users/')
            finally:
                context.close()
            # Shut the browser down completely. The fixture now refuses every
            # network request while navigator.onLine remains true, like an outage.
            unavailable.set()
            context = pw.chromium.launch_persistent_context(profile, headless=True, **browser_options)
            try:
                page = context.pages[0]
                response = page.goto(base)
                assert response.from_service_worker
                assert response.headers.get('x-pwa-local') == '1'
                assert page.locator('[data-pwa-local]').count() == 1
                response = page.goto(base + '/invoices/')
                assert response.headers.get('x-pwa-local') == '1'
                retained = page.evaluate("""async () => {
                    const db=await import('/static/js/pwa/db.js');
                    return {rows:await db.getAll(db.STORE_NAMES.syncQueue),device:await db.getDeviceId()};
                }""")
                assert retained['device'] == operation['device']
                assert len(retained['rows']) == 1
                assert retained['rows'][0]['idempotency_key'] == operation['key']
                assert retained['rows'][0]['id'] == operation['id']
                print('PASS: full browser restart during server outage preserves the shell, queued data and retry identity', flush=True)
            finally:
                context.close()
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


if __name__ == '__main__':
    main()
