"""Render representative real pages against an isolated database using Playwright.

Run: .venv-audit/Scripts/python.exe tests/ui_review.py --output build/ui-review
Use --baseline to record layout findings without failing the run.
"""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from wsgiref.simple_server import WSGIRequestHandler, make_server


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='build/ui-review')
    parser.add_argument('--baseline', action='store_true')
    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='sh-ui-') as temporary, ExitStack() as cleanup:
        os.environ.update(
            DJANGO_SETTINGS_MODULE='config.settings', DB_ENGINE='sqlite',
            SQLITE_PATH=str(Path(temporary) / 'preview.sqlite3'), DEBUG='True',
            ALLOWED_HOSTS='127.0.0.1,localhost,testserver', LOG_TO_FILE='False',
            EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        )
        import django
        django.setup()
        from django.contrib.staticfiles.handlers import StaticFilesHandler
        from django.core.management import call_command
        from django.core.wsgi import get_wsgi_application
        from django.db import connections
        cleanup.callback(connections.close_all)
        from django.test import Client
        from django.urls import reverse
        from accounts.models import User
        from customers.models import Customer
        from finance.models import CashAccount
        from inventory.models import Warehouse
        from inventory.services import stock_in
        from invoices.services import generate_invoice
        from orders.models import Order
        from orders.services import create_order
        from products.models import Product, ProductVariant
        from purchases.models import Supplier

        call_command('migrate', interactive=False, verbosity=0)
        user = User.objects.create_superuser(username='ui-preview', password='local-preview-only', first_name='مستخدم المعاينة')
        customer = Customer.objects.create(name='شركة النور لتجارة الملابس', phone='01012345678', created_by=user)
        Supplier.objects.create(name='مورد المعاينة')
        warehouse = Warehouse.objects.create(name='المخزن الرئيسي')
        CashAccount.get_default()
        variants = []
        for index, name in enumerate(['قميص قطن كلاسيك', 'بنطلون جينز رجالي', 'تيشيرت صيفي', 'جاكيت شتوي']):
            product = Product.objects.create(name=name, sku=f'PREVIEW-{index}', retail_price=300, wholesale_price=250)
            variant = ProductVariant.objects.create(product=product, variant_sku=f'PREVIEW-{index}-M',
                                                    cost_price=100, retail_price=300, wholesale_price=250)
            stock_in(variant=variant, warehouse=warehouse, quantity=30, user=user, unit_cost=100)
            variants.append(variant)
        order = create_order(order_data=dict(customer=customer, warehouse=warehouse, order_type=Order.TYPE_B2C,
                                             payment_method=Order.METHOD_CREDIT),
                             items=[dict(variant=variant, warehouse=warehouse, quantity=2, unit_price=300)
                                    for variant in variants], user=user, confirm=True)
        invoice = generate_invoice(order, user=user)
        client = Client()
        client.force_login(user)
        session = client.cookies['sessionid'].value

        class QuietHandler(WSGIRequestHandler):
            def log_message(self, *unused):
                pass

        server = make_server('127.0.0.1', 0, StaticFilesHandler(get_wsgi_application()), handler_class=QuietHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        pages = {
            'dashboard': reverse('dashboard:index'),
            'sale': reverse('orders:create'),
            'products': reverse('products:list'),
            'product-form': reverse('products:create'),
            'customers': reverse('customers:simple_list'),
            'customer-form': reverse('customers:simple_create'),
            'customer-detail': reverse('customers:simple_detail', args=[customer.pk]),
            'cash': reverse('finance:cash'),
            'returns': reverse('returns:customer_create') + f'?customer={customer.pk}',
            'stock': reverse('inventory:stock'),
            'stock-form': reverse('inventory:stock_in'),
            'invoices': reverse('invoices:list'),
            'invoice-detail': reverse('invoices:detail', args=[invoice.pk]),
            'purchases': reverse('purchases:orders'),
            'purchase-form': reverse('purchases:order_create'),
            'reports': reverse('reports:index'),
        }
        results = []
        from playwright.sync_api import sync_playwright
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(service_workers='block', reduced_motion='reduce')
                context.add_cookies([dict(name='sessionid', value=session, url=base)])
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                for width, height in [(390, 844), (768, 1024), (1024, 768), (1280, 800),
                                      (1366, 768), (1536, 864), (1920, 1080), (2560, 1440)]:
                    page.set_viewport_size(dict(width=width, height=height))
                    for name, path in pages.items():
                        response = page.goto(base + path, wait_until='networkidle')
                        assert response.status == 200, (name, response.status)
                        page.evaluate('document.fonts.ready')
                        metrics = page.evaluate(LAYOUT_METRICS)
                        results.append(dict(page=name, width=width, **metrics))
                        if name in {'dashboard', 'sale', 'cash', 'returns'} and width in {390, 1024, 1366, 1920}:
                            page.screenshot(path=str(output / f'{name}-{width}.png'), full_page=True)
                    findings = [r for r in results if r['width'] == width and (r['overflow'] > 2 or r['overlaps'] or r['clipped'] or r['cramped'])]
                    print(json.dumps(dict(width=width, pages=len(pages), findings=findings), ensure_ascii=True), flush=True)
                # Existing controls remain usable after the layout changes.
                page.set_viewport_size(dict(width=1366, height=768))
                page.goto(base + pages['sale'], wait_until='networkidle')
                page.locator('[data-open-modal="customer-modal"]').click()
                assert page.locator('#customer-modal').is_visible()
                page.locator('#customer-modal [data-close-modal]').first.click()
                assert not page.locator('#customer-modal').is_visible()
                page.locator('#product-search').fill('PREVIEW-0')
                page.locator('.search-result[data-id]').filter(has_text='PREVIEW-0').first.click()
                variant_combo = page.locator('.combo-field').filter(has=page.locator('#variant-select'))
                variant_combo.locator('.combo-input').click()
                variant_combo.locator('.combo-option').filter(has_text='PREVIEW-0-M').click()
                page.locator('#add-item').click()
                assert page.locator('#order-items-body').inner_text().find('قميص قطن كلاسيك') >= 0
                assert page.locator('#summary-total').inner_text() != '0.00'
                page.goto(base + pages['returns'], wait_until='networkidle')
                page.locator('input[name^="selected_"]').first.check()
                page.locator('#purchase-search').fill('PREVIEW-1')
                assert page.locator('[data-purchase-row]:visible').count() == 1
                assert page.locator('input[name^="selected_"]').first.is_checked()
                page.locator('#purchase-search').fill('')
                page.set_viewport_size(dict(width=390, height=844))
                page.locator('[data-sidebar-toggle]').click()
                assert page.locator('body').evaluate("element => element.classList.contains('sidebar-open')")
                page.locator('.sidebar [data-sidebar-close]').click()
                assert not page.locator('body').evaluate("element => element.classList.contains('sidebar-open')")
                page.emulate_media(media='print')
                assert not page.locator('.sidebar').is_visible()
                browser.close()
            (output / 'report.json').write_text(json.dumps(dict(results=results, javascript_errors=errors), indent=2), encoding='utf-8')
            assert not errors, errors
            if not args.baseline:
                failures = [r for r in results if r['overflow'] > 2 or r['overlaps'] or r['clipped'] or r['cramped']]
                assert not failures, json.dumps(failures, ensure_ascii=True)
            print(f'Checked {len(results)} page/viewport combinations; interaction and print checks passed.', flush=True)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            connections.close_all()


LAYOUT_METRICS = r'''() => {
    const visible = element => {
        const rect = element.getBoundingClientRect();
        const style = getComputedStyle(element);
        return rect.width > 1 && rect.height > 1 && style.visibility !== 'hidden' && style.display !== 'none';
    };
    const describe = element => element.id || element.className || element.tagName;
    const overlaps = [];
    for (const group of document.querySelectorAll('.page-head,.actions,.button-row,.form-actions,.filters,.form-grid,.invoice-info,.quantity-section,.cashier-grid,.invoice-actions,.topbar')) {
        const children = [...group.children].filter(el => visible(el) && !['absolute','fixed'].includes(getComputedStyle(el).position));
        for (let i=0; i<children.length; i++) for (let j=i+1; j<children.length; j++) {
            const a=children[i].getBoundingClientRect(), b=children[j].getBoundingClientRect();
            if (Math.min(a.right,b.right)-Math.max(a.left,b.left)>2 && Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>2)
                overlaps.push(`${describe(group)}: ${describe(children[i])} / ${describe(children[j])}`);
        }
    }
    const clipped = [];
    for (const input of document.querySelectorAll('.page-content input,.page-content select,.page-content textarea,.page-content .btn')) {
        if (!visible(input) || input.classList.contains('combo-source') || input.closest('.responsive-table-region,.table-wrap,.items-table-wrap,.invoice-items,.stock-table-wrap,.cash-table-wrap,.modal')) continue;
        const container=input.closest('.card,.filters,.filter-section,.items-section,.simple-form');
        if (!container || !visible(container)) continue;
        const a=input.getBoundingClientRect(), b=container.getBoundingClientRect();
        if (a.left < b.left-2 || a.right > b.right+2) clipped.push(describe(input));
    }
    const content=document.querySelector('.page-content');
    const cramped = [...document.querySelectorAll('.page-content .btn')].filter(el => visible(el) && el.scrollWidth > el.clientWidth + 2).map(describe);
    return {overflow:Math.max(document.documentElement.scrollWidth-innerWidth,content.scrollWidth-content.clientWidth),overlaps,clipped,cramped};
}'''


if __name__ == '__main__':
    main()
