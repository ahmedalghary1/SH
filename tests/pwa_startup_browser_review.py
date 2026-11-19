"""Initial app launch, before any data download/reload, in a disposable browser.

Set PWA_BROWSER_EXECUTABLE to test the installed Brave binary on Windows.
"""
from django.test import Client

from pwa_browser_review import main, wait_for


def review(browser, base, unavailable):
    from accounts.models import User
    from inventory.models import Warehouse
    from inventory.services import stock_in
    from invoices.models import Invoice
    from orders.models import Order
    from products.models import Product, ProductVariant
    from sync_api.models import SyncOperation

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

    manager = User.objects.get(username='pwa-test')
    warehouse = Warehouse.objects.get(name='PWA warehouse')
    for index in range(12):
        product = Product.objects.create(name=f'Catalog product {index}', sku=f'CAT-PWA-{index}')
        variant = ProductVariant.objects.create(
            product=product, variant_sku=f'CAT-V-{index}', barcode=f'9876543210{index}',
            retail_price=30, cost_price=10,
        )
    stock_in(variant=variant, warehouse=warehouse, quantity=5, unit_cost=10, user=manager)
    client = Client()
    client.force_login(manager)
    catalog_page = client.get('/orders/ajax/search-products/?offset=10').json()
    assert variant.product_id in [row['id'] for row in catalog_page['data']]
    assert not catalog_page['has_more']
    barcode_match = client.get('/orders/ajax/search-products/?q=987654321011').json()
    assert [row['id'] for row in barcode_match['data']] == [variant.product_id]
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

        # No prior visit to these lists or the statement. The server outage
        # leaves navigator.onLine true throughout navigation and invoice entry.
        unavailable.set()
        release_images()
        page.close()
        page = context.new_page()
        context.new_cdp_session(page).send('Network.clearBrowserCache')
        response = page.goto(base + '/invoices/', wait_until='domcontentloaded')
        assert response.from_service_worker and page.evaluate('navigator.onLine')
        page.wait_for_selector('[data-local-data-view]')
        assert page.locator('.page-head').evaluate("(el) => getComputedStyle(el).display") == 'flex'
        assert page.locator('body').evaluate("(el) => getComputedStyle(el).fontFamily").startswith('Cairo')
        assert page.locator('[data-page-content] .invoice-navigation').count() == 1
        page.evaluate("window.SHWorkspace.navigate('/customers/')")
        page.wait_for_selector('[data-local-data-view] .page-head a[href="/customers/simple/create/"]')
        page.evaluate("window.SHWorkspace.navigate('/finance/statements/customer/')")
        page.wait_for_function("getComputedStyle(document.querySelector('.statement-head') || document.body).display === 'flex'")
        page.evaluate("window.SHWorkspace.navigate('/invoices/')")
        page.locator('a.btn[href="/orders/create/"]').click()
        page.wait_for_selector('#order-form[data-order-ready]')
        page.locator('#invoice-kind').evaluate("""select => {
            select.value = 'retail';
            select.dispatchEvent(new Event('change', {bubbles:true}));
        }""")
        page.locator('#product-search').focus()
        page.locator('[data-product-offset]').click()
        page.locator('#product-results .search-result').filter(has_text='CAT-PWA-11').wait_for()
        page.locator('#product-search').fill('987654321011')
        matching = page.locator('#product-results .search-result')
        matching.filter(has_text='CAT-PWA-11').wait_for()
        page.wait_for_function("document.querySelectorAll('#product-results .search-result').length === 1")
        matching.click()
        page.wait_for_function("(id) => !!document.querySelector(`#variant-select option[value='${id}']`)", arg=variant.pk)
        page.locator('#variant-select').evaluate("(select, id) => {select.value = id; select.dispatchEvent(new Event('change', {bubbles:true}));}", str(variant.pk))
        page.wait_for_function("(id) => document.querySelector('#item-warehouse').value === id", arg=str(warehouse.pk))
        page.locator('#add-item').click()
        assert 'Catalog product 11' in page.locator('#order-items-body').inner_text()
        page.locator('#order-form button[value="confirm"]').click()
        page.wait_for_function("document.querySelector('#order-form').dataset.offlineQueued === 'true'")
        queued = page.evaluate("""async () => {
            const db = await import('/static/js/pwa/db.js');
            return await db.getAll(db.STORE_NAMES.syncQueue);
        }""")
        assert len(queued) == 1 and queued[0]['payload']['order']['action'] == 'confirm', queued
        assert not Invoice.objects.exists()
        unavailable.clear()
        page.evaluate('window.SHSync.processQueue()')
        wait_for(page, """async () => {
            const db = await import('/static/js/pwa/db.js');
            return !(await db.getAll(db.STORE_NAMES.syncQueue)).length;
        }""")
        assert Invoice.objects.filter(order__items__variant=variant, order__customer__isnull=True).count() == 1, (
            list(Order.objects.values('id', 'status', 'document_type')),
            list(SyncOperation.objects.values_list('response_json', flat=True)),
        )
        print('PASS: cached CSS, add actions, complete catalog and invoice entry survive a cold offline page load', flush=True)
    finally:
        unavailable.clear()
        release_images()
        context.close()

    # Realistic existing administrator: profile assigned to one branch, UI set
    # to all branches. This must not send a branch-specific scope to the API.
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
