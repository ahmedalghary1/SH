"""Verify the offline invoice flow in one engine with a disposable database.

Set PWA_BROWSER_ENGINE=firefox for Gecko or PWA_BROWSER_EXECUTABLE to exercise
an installed Chromium browser such as Chrome or Edge.
"""
from django.test import Client

from pwa_browser_review import main, wait_for


def review(browser, base, unavailable):
    from accounts.models import User
    from invoices.models import Invoice

    print(f'{browser.browser_type.name} {browser.version}', flush=True)
    client = Client()
    client.force_login(User.objects.get(username='pwa-test'))
    context = browser.new_context()
    context.add_cookies([dict(name='sessionid', value=client.cookies['sessionid'].value, url=base)])
    errors = []
    try:
        page = context.new_page()
        page.goto(base + '/', wait_until='domcontentloaded')
        page.wait_for_function('window.SHSync?.isOfflineReady()', timeout=90000)
        page.wait_for_function('Boolean(navigator.serviceWorker.controller)')
        page.close()
        unavailable.set()
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        if browser.browser_type.name == 'chromium':
            session = context.new_cdp_session(page)
            session.send('Network.clearBrowserCache')
            session.detach()
        page.goto(base + '/invoices/', wait_until='domcontentloaded')
        page.wait_for_selector('[data-pwa-local][data-local-data-view]')
        page.wait_for_function("""() => {
            const heading = document.querySelector('[data-page-content] .page-head');
            const primaryFont = getComputedStyle(document.body).fontFamily.split(',')[0].replace(/['"]/g, '').trim();
            return heading && getComputedStyle(heading).display === 'flex' && primaryFont === 'Cairo';
        }""")
        page.locator('[data-page-content] .page-head a[href="/orders/create/"]').click()
        page.wait_for_selector('#order-form[data-order-ready]')
        page.locator('#invoice-kind').evaluate("""select => {
            select.value = 'retail';
            select.dispatchEvent(new Event('change', {bubbles: true}));
        }""")
        page.locator('#product-search').fill('PWA-TEST')
        page.locator('#product-results .search-result').filter(has_text='PWA-TEST').click()
        page.wait_for_selector('#variant-select option[value]:not([value=""])', state='attached')
        page.locator('#variant-select').evaluate("""select => {
            select.selectedIndex = 1;
            select.dispatchEvent(new Event('change', {bubbles: true}));
        }""")
        page.wait_for_function("document.querySelector('#unit-price').value === '30.00'")
        page.locator('#add-item').click()
        assert 'PWA product' in page.locator('#order-items-body').inner_text()
        page.locator('#order-form button[value="confirm"]').click()
        page.wait_for_function("document.querySelector('#order-form').dataset.offlineQueued === 'true'")
        assert not Invoice.objects.exists()
        unavailable.clear()
        page.evaluate('window.SHSync.processQueue()')
        wait_for(page, """async () => {
            const db = await import('/static/js/pwa/db.js');
            return !(await db.getAll(db.STORE_NAMES.syncQueue)).length;
        }""")
        assert Invoice.objects.count() == 1
        assert not errors, errors
        print('PASS: offline CSS, invoice navigation, local product, and exactly-once synchronization', flush=True)
    finally:
        unavailable.clear()
        context.close()


if __name__ == '__main__':
    main(review)
