"""Initial app launch, before any data download/reload, in a disposable browser.

Set PWA_BROWSER_EXECUTABLE to test the installed Brave binary on Windows.
"""
from django.test import Client

from pwa_browser_review import main


def review(browser, base, unavailable):
    from accounts.models import User

    # Browser UI can install the manifest even before the first sign-in.
    public = browser.new_context()
    try:
        page = public.new_page()
        page.goto(base + '/accounts/login/', wait_until='domcontentloaded')
        page.wait_for_function("async () => !!(await navigator.serviceWorker.getRegistration('/'))?.active", timeout=15000)
        page.wait_for_function('!!navigator.serviceWorker.controller')
        unavailable.set()
        response = page.goto(base + '/')
        assert response.from_service_worker
        assert page.locator('h1').inner_text()
        assert len(page.locator('body').inner_text()) > 60
        print('PASS: first signed-out launch shows an offline explanation, never an empty network page', flush=True)
    finally:
        unavailable.clear()
        public.close()

    client = Client()
    client.force_login(User.objects.get(username='pwa-test'))
    context = browser.new_context()
    pending_images = []
    context.route('**/__pwa_slow_image__', lambda route: pending_images.append(route))

    def release_images():
        while pending_images:
            pending_images.pop(0).fulfill(status=204, body='')
    context.add_init_script("""
        window.addEventListener('load', () => {window.startupLoaded = true;});
        document.addEventListener('DOMContentLoaded', () => {
            const image = new Image(); image.src = '/__pwa_slow_image__'; document.body.append(image);
        }, {once:true});
    """)
    context.add_cookies([dict(name='sessionid', value=client.cookies['sessionid'].value, url=base)])
    context.route('**/api/sync/bootstrap-browser/', lambda route: route.fulfill(
        status=503, content_type='application/json', body='{"error":"Delayed first snapshot"}'))
    try:
        page = context.new_page()
        page.goto(base + '/orders/create/', wait_until='domcontentloaded')
        page.wait_for_function('!!window.SHSync')
        page.evaluate('window.SHSync.cacheAppShell()')
        prepared = page.evaluate("""async () => {
            const scope=(await import('/static/js/pwa/identity.js')).getOfflineScope();
            const cache=await caches.open('sh-pwa-pages-v2-'+scope);
            return !!await cache.match(location.origin+'/', {ignoreVary:true});
        }""")
        assert prepared, 'The launch URL must be cached independently of the first bootstrap'
        assert not page.evaluate('Boolean(window.startupLoaded)'), 'Offline preparation must not wait for image/window load'
        assert not page.evaluate('window.SHSync.isOfflineReady()')
        unavailable.set()
        release_images()
        page.close()
        page = context.new_page()
        response = page.goto(base + '/?source=installed', wait_until='domcontentloaded')
        assert response.from_service_worker
        page.wait_for_selector('#main-content h1')
        assert page.locator('[data-pwa-local]').count() == 1
        print('PASS: first authenticated launch survives an interrupted bootstrap and opens its scoped shell offline', flush=True)
        unavailable.clear()
        context.unroute('**/api/sync/bootstrap-browser/')
        page.evaluate('window.SHSync.bootstrapNow()')
        page.wait_for_function('window.SHSync.isOfflineReady()', timeout=90000)
        print('PASS: reconnect completes the snapshot and required screens before enabling offline installation', flush=True)
    finally:
        unavailable.clear()
        release_images()
        context.close()

    # Realistic existing administrator: profile assigned to one branch, UI set
    # to all branches. This must not send a branch-specific scope to the API.
    manager = User.objects.get(username='pwa-test')
    administrator = User.objects.create_superuser(username='all-branches-ready', branch_id=manager.branch_id)
    client.force_login(administrator)
    context = browser.new_context()
    context.add_cookies([dict(name='sessionid', value=client.cookies['sessionid'].value, url=base)])
    try:
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        response = page.goto(base + '/', wait_until='domcontentloaded')
        page.wait_for_function('window.SHSync?.isOfflineReady?.()', timeout=90000)
        scope = page.evaluate("async () => (await import('/static/js/pwa/identity.js')).getOfflineScope()")
        assert scope == f'u{administrator.pk}-ball-r{administrator.role}-s1'
        assert response.headers['x-pwa-scope'] == scope
        status = page.evaluate('window.SHSync.getOfflineReadiness()')
        assert status['ready'] and not status['failed'], status
        assert not page.locator('[data-offline-ready]').get_attribute('title')
        # Verify that a genuine eligibility event enables a real DOM button.
        page.evaluate("""() => {
            const event=new Event('beforeinstallprompt');
            event.prompt=async()=>{}; event.userChoice=Promise.resolve({outcome:'dismissed'});
            window.dispatchEvent(event);
        }""")
        page.wait_for_function("!document.querySelector('[data-pwa-install]').hidden && !document.querySelector('[data-pwa-install]').disabled")
        assert not errors, errors
        print('PASS: assigned administrator in all-branches mode completes offline preparation and enables installation in Brave', flush=True)
    finally:
        context.close()


if __name__ == '__main__':
    main(review)
