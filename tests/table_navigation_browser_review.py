"""Exercise shared row navigation in a real DOM without modifying app data."""
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
HTML = '''<section data-page-content><table><thead><tr><th>Header</th></tr></thead><tbody>
<tr id="product"><td>Product</td><td><a href="/products/1/update/">Edit</a><a href="/products/1/">عرض</a><input type="checkbox"><button>Action</button><label>Choose</label></td></tr>
<tr id="explicit" data-row-link="/invoices/2/"><td>Invoice</td><td><a href="/customers/3/">Customer</a><a href="/invoices/2/">عرض</a></td></tr>
<tr id="related"><td>Order</td><td><a href="/orders/4/">ORD-4</a></td></tr>
<tr id="delete"><td>Delete only</td><td><a href="/returns/3/delete/">Delete</a></td></tr>
<tr id="total" class="table-total-row"><td>Total</td></tr>
<tr id="entry"><td><input value="1"></td></tr>
</tbody></table></section>'''


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('http://rows.test/**', lambda route: route.fulfill(body=HTML, content_type='text/html'))
            page.goto('http://rows.test/')
            page.evaluate('''() => {
                window.visits = [];
                document.addEventListener('click', event => {
                    const link = event.target.closest('a');
                    if (link) { event.preventDefault(); visits.push(link.getAttribute('href')); }
                });
            }''')
            page.add_script_tag(path=str(ROOT / 'static/js/table-navigation.js'))
            page.locator('#product td').first.click()
            assert page.evaluate('visits.pop()') == '/products/1/'
            page.locator('#explicit td').first.click()
            assert page.evaluate('visits.pop()') == '/invoices/2/'
            page.locator('#related').focus()
            page.keyboard.press('Enter')
            assert page.evaluate('visits.pop()') == '/orders/4/'
            page.keyboard.press('Space')
            assert page.evaluate('visits.pop()') == '/orders/4/'
            for selector in ['#product input', '#product button', '#product label', '#delete td:first-child', '#total td', '#entry input']:
                page.locator(selector).click()
                assert page.evaluate('visits.length') == 0, selector
            page.locator('#product a').first.click()
            assert page.evaluate('visits.pop()') == '/products/1/update/'
            page.evaluate('''() => document.querySelector('tbody').insertAdjacentHTML('beforeend',
                '<tr id="dynamic"><td>New offline row</td><td><a href="/purchases/orders/9/">PO-9</a></td></tr>')''')
            page.wait_for_selector('#dynamic[data-row-link]')
            page.locator('#dynamic td').first.click()
            assert page.evaluate('visits.pop()') == '/purchases/orders/9/'
            page.evaluate('''() => {
                const range = document.createRange(); range.selectNodeContents(document.querySelector('#product td'));
                getSelection().removeAllRanges(); getSelection().addRange(range);
                document.querySelector('#product td').dispatchEvent(new MouseEvent('click', {bubbles:true, button:0}));
            }''')
            assert page.evaluate('visits.length') == 0
            assert not errors, errors
            print('PASS: details priority, explicit target, keyboard, controls, edit links, dynamic/offline rows, text selection; no JavaScript errors')
        finally:
            browser.close()


if __name__ == '__main__':
    main()
