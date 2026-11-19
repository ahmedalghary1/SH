"""Check row sorting in a browser. Pass chrome, msedge or firefox to select an engine."""
from pathlib import Path
import sys

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
HTML = """<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><section data-page-content>
<table><thead><tr><th>الاسم</th><th>المبلغ</th><th>التاريخ</th><th>اختيار</th></tr></thead><tbody>
<tr id="a"><td>جمال</td><td>٩٬٠٠٧٬١٩٩٬٢٥٤٬٧٤٠٬٩٩٣٫٠٢ ج.م</td><td>الاثنين، ٢ يناير ٢٠٢٣، ١٢:١٥ م</td><td><input type="checkbox"></td></tr>
<tr id="b"><td>أحمد</td><td>9007199254740993.01</td><td>الاثنين، ٢ يناير ٢٠٢٣، ١٢:٣٠ ص</td><td></td></tr>
<tr id="c"><td>باسم</td><td>-۲٫۵</td><td>ديسمبر 31, 2022, 1:10 م</td><td></td></tr>
<tr id="d"><td>دينا</td><td>—</td><td>—</td><td></td></tr>
<tr data-no-match hidden><td colspan="4">لا توجد نتائج</td></tr></tbody>
<tfoot><tr><th colspan="4">الإجمالي</th></tr></tfoot></table></section></html>"""


def review(browser):
    page = browser.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.route('http://tables.test/**', lambda route: route.fulfill(body=HTML, content_type='text/html'))
    page.goto('http://tables.test/')
    page.add_style_tag(path=str(ROOT / 'static/css/table-controls.css'))
    for name in ('main', 'table-controls'):
        page.add_script_tag(path=str(ROOT / f'static/js/{name}.js'))
    page.evaluate("document.dispatchEvent(new Event('sh:page-loaded'))")
    rows = page.locator('tbody tr[id]')
    amount = page.get_by_role('button', name='ترتيب حسب المبلغ')
    ids = lambda: rows.evaluate_all('(rows) => rows.map(r => r.id).join("")')
    page.locator('#a input').check()
    amount.click()
    assert ids() == 'cbad'
    assert page.locator('th[aria-sort="ascending"]').inner_text() == 'المبلغ'
    assert '↑' in amount.evaluate("(el) => getComputedStyle(el, '::after').content")
    amount.press('Enter')
    assert ids() == 'abcd'
    page.get_by_role('button', name='ترتيب حسب التاريخ').click()
    assert ids() == 'cbad'
    page.get_by_role('button', name='ترتيب حسب الاسم').click()
    assert ids() == 'bcad'
    assert page.locator('#a input').is_checked()
    assert page.locator('tbody tr:last-child').get_attribute('data-no-match') is not None
    assert page.locator('tfoot th').inner_text() == 'الإجمالي'
    page.locator('.table-column-control summary').click()
    page.locator('.table-column-control').get_by_label('الاسم').uncheck()
    amount.click()
    page.eval_on_selector('tbody', """body => body.insertAdjacentHTML('beforeend',
        '<tr id="e"><td>وليد</td><td>10</td><td>2020-12-31</td><td></td></tr>')""")
    page.wait_for_function("document.querySelector('.table-record-count').textContent.endsWith('5')")
    assert ids() == 'cebad'
    assert not page.locator('#e td').first.is_visible()
    page.eval_on_selector('[data-page-content]', """root => root.innerHTML =
        '<table><thead><tr><th>الوقت</th></tr></thead><tbody><tr><td>١:٠٠ م</td></tr>' +
        '<tr><td>٢:٠٠ ص</td></tr></tbody></table>'""")
    page.get_by_role('button', name='ترتيب حسب الوقت').click()
    assert page.locator('tbody td').first.inner_text() == '٢:٠٠ ص'
    assert page.locator('.table-record-count').count() == 1
    assert not errors, errors


if __name__ == '__main__':
    name = sys.argv[1] if len(sys.argv) > 1 else 'chromium'
    with sync_playwright() as pw:
        if name == 'firefox':
            browser = pw.firefox.launch()
        else:
            browser = pw.chromium.launch(channel=None if name == 'chromium' else name)
        try:
            review(browser)
            print(f'PASS {name} {browser.version}')
        finally:
            browser.close()
