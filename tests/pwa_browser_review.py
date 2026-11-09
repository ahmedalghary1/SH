"""Exercise real Chromium IndexedDB, offline navigation and server sync.
Run with .venv-audit/Scripts/python.exe tests/pwa_browser_review.py
Uses an isolated temporary database; never reads or writes production data.
"""
from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from wsgiref.simple_server import make_server, WSGIRequestHandler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def wait_for(page, expression):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if page.evaluate(expression):
            return
        page.wait_for_timeout(100)
    raise AssertionError('Timed out: ' + expression)


def main():
    with tempfile.TemporaryDirectory(prefix='sh-pwa-') as temporary, ExitStack() as cleanup:
        os.environ.update(DJANGO_SETTINGS_MODULE='config.settings', DB_ENGINE='sqlite',
                          SQLITE_PATH=str(Path(temporary) / 'test.sqlite3'), DEBUG='True',
                          ALLOWED_HOSTS='127.0.0.1,localhost,testserver', LOG_TO_FILE='False',
                          DJANGO_ALLOW_ASYNC_UNSAFE='true')
        import django
        django.setup()
        from django.core.management import call_command
        from django.contrib.staticfiles.handlers import StaticFilesHandler
        from django.core.wsgi import get_wsgi_application
        from django.db import connections
        from django.test import Client
        from accounts.models import User
        from inventory.models import Warehouse, Stock
        from inventory.services import stock_in
        from products.models import Product, ProductVariant
        from customers.models import Customer
        from orders.models import Order
        from invoices.models import Invoice
        from playwright.sync_api import sync_playwright
        cleanup.callback(connections.close_all)
        call_command('migrate', interactive=False, verbosity=0)
        user = User.objects.create_user(username='pwa-test', role='manager')
        warehouse = Warehouse.objects.create(name='PWA warehouse')
        target = Warehouse.objects.create(name='Target warehouse')
        customer = Customer.objects.create(name='PWA customer', created_by=user)
        product = Product.objects.create(name='PWA product', sku='PWA-TEST')
        variant = ProductVariant.objects.create(product=product, variant_sku='PWA-V', retail_price=30, cost_price=10)
        stock_in(variant=variant, warehouse=warehouse, quantity=10, unit_cost=10, user=user)
        client = Client()
        client.force_login(user)

        class QuietHandler(WSGIRequestHandler):
            def log_message(self, *unused):
                pass

        server = make_server('127.0.0.1', 0, StaticFilesHandler(get_wsgi_application()), handler_class=QuietHandler)
        def serve():
            try:
                server.serve_forever()
            finally:
                connections.close_all()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        cleanup.callback(server.server_close)
        cleanup.callback(thread.join)
        cleanup.callback(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}'
        with sync_playwright() as playwright, ExitStack() as browser_cleanup:
            browser = playwright.chromium.launch(headless=True)
            browser_cleanup.callback(browser.close)
            browser_cleanup.callback(connections.close_all)
            context = browser.new_context()
            context.add_cookies([dict(name='sessionid', value=client.cookies['sessionid'].value, url=base)])
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/orders/create/', wait_until='networkidle')
            wait_for(page, "window.SHSync && window.SHOffline")
            page.evaluate("async () => { window.db = await import('/static/js/pwa/db.js'); await window.SHSync.bootstrapNow(); await navigator.serviceWorker.ready; }")
            wait_for(page, "async () => !!await db.getMetadata('last_bootstrap_at')")
            wait_for(page, "!!navigator.serviceWorker.controller")
            page.evaluate("window.fixture = " + str(dict(variant=variant.pk, warehouse=warehouse.pk, target=target.pk, customer=customer.pk)))
            page.evaluate("""() => {
                window.stockKey = `${fixture.warehouse}:${fixture.variant}`;
                window.sale = (id, quantity) => ({id, local_uuid:id, original_url:'/orders/create/',
                    order:{customer_server_id:fixture.customer, warehouse:fixture.warehouse,
                           action:'confirm', document_type:'sale', payment_method:'credit'},
                    items:[{variant_id:fixture.variant, warehouse_id:fixture.warehouse, quantity, unit_price:'30'}]});
                window.enqueueSale = (id, quantity) => db.queueEntityOperation('sales', 'create_invoice', sale(id,quantity), {
                    entity_type:'order', stock_mutations:[{variant_id:fixture.variant, warehouse_id:fixture.warehouse, delta:-quantity}]});
            }""")
            context.set_offline(True)
            # Duplicate item lines must aggregate and reject overselling atomically.
            result = page.evaluate("""async () => {
                try { await db.queueEntityOperation('sales','create_invoice',sale('oversell',12), {entity_type:'order',
                    stock_mutations:[{variant_id:fixture.variant,warehouse_id:fixture.warehouse,delta:-6},
                                     {variant_id:fixture.variant,warehouse_id:fixture.warehouse,delta:-6}]}); }
                catch (e) { return {error:e.message, queue:(await db.getAll(db.STORE_NAMES.syncQueue)).length,
                    sales:(await db.getAll(db.STORE_NAMES.sales)).filter(x=>x.id==='oversell').length,
                    stock:(await db.getRecord(db.STORE_NAMES.stock,stockKey)).quantity}; }
            }""")
            assert result['error'] and result['queue'] == result['sales'] == 0 and result['stock'] == 10, result
            # Concurrent local sales use real read/write transaction serialization.
            result = page.evaluate("""async () => {
                const results = await Promise.allSettled([enqueueSale('sale-a',6),enqueueSale('sale-b',6)]);
                return {accepted:results.filter(x=>x.status==='fulfilled').length,
                        queue:(await db.getAll(db.STORE_NAMES.syncQueue)).length,
                        stock:(await db.getRecord(db.STORE_NAMES.stock,stockKey)).quantity};
            }""")
            assert result == dict(accepted=1, queue=1, stock=4), result
            # A download containing the original stock cannot erase the reservation.
            result = page.evaluate("""async () => {
                const scope = (await import('/static/js/pwa/identity.js')).getOfflineScope();
                const imported = await db.importBootstrap({scope,stock:[{warehouse_id:fixture.warehouse,variant_id:fixture.variant,quantity:10}]});
                return {imported,stock:(await db.getRecord(db.STORE_NAMES.stock,stockKey)).quantity};
            }""")
            assert result == dict(imported=False, stock=4), result
            print('PASS: atomic stock/invoice/queue, concurrent sale rejection, pending snapshot protection', flush=True)
            # Simulate server commit with a lost response, then safely retry the same key.
            page.evaluate("""() => {
                const original=window.fetch;
                window.lostStatuses=[];
                let dropped=false;
                window.fetch=async (...args) => {
                    const response=await original(...args);
                    if (!dropped && String(args[0]).includes('/api/sync/sales/')) {
                        dropped=true; window.lostStatuses.push(response.status);
                        throw new TypeError('Simulated lost acknowledgement');
                    }
                    return response;
                };
            }""")
            context.set_offline(False)
            wait_for(page, 'navigator.onLine')
            page.evaluate('window.SHSync.processQueue()')
            wait_for(page, "async () => (await db.getAll(db.STORE_NAMES.syncQueue))[0]?.status === 'failed'")
            lost = page.evaluate("window.lostStatuses")
            assert lost == [200], (lost, page.evaluate("(async () => await db.getAll(db.STORE_NAMES.syncQueue))()"))
            assert Invoice.objects.count() == 1
            assert Stock.objects.get(warehouse=warehouse, variant=variant).quantity == 4
            page.evaluate("""async () => {
                for (const item of await db.getAll(db.STORE_NAMES.syncQueue)) await db.putRecord(db.STORE_NAMES.syncQueue,{...item,status:'pending',next_attempt_at:db.nowIso()});
                await window.SHSync.processQueue();
            }""")
            wait_for(page, "async () => !(await db.getAll(db.STORE_NAMES.syncQueue)).length")
            assert Invoice.objects.count() == Order.objects.count() == 1
            assert Stock.objects.get(warehouse=warehouse, variant=variant).quantity == 4
            assert page.evaluate('(async () => (await db.getRecord(db.STORE_NAMES.stock,stockKey)).quantity)()') == 4
            result = page.evaluate("""async () => {
                const scope=(await import('/static/js/pwa/identity.js')).getOfflineScope();
                return db.importBootstrap({scope,stock:[{warehouse_id:fixture.warehouse,variant_id:fixture.variant,quantity:10}]},
                                          {expectedQueueRevision:0});
            }""")
            assert result is False, 'A stale download must be rejected even after the queue has emptied'
            print('PASS: lost server acknowledgement replays once, one invoice and correct final stock', flush=True)
            context.set_offline(True)
            # Use the actual invoice serializer, including the button named action.
            result = page.evaluate("""async () => {
                const form=document.getElementById('order-form');
                form.elements.customer.value=fixture.customer;
                form.elements.warehouse.value=fixture.warehouse;
                form.elements.payment_method.value='credit';
                form.elements.items_json.value=JSON.stringify(sale('form-sale',1).items);
                await window.SHOffline.queueFormSubmission(form,form.querySelector('[name="action"][value="confirm"]'));
                return (await db.getRecord(db.STORE_NAMES.stock,stockKey)).quantity;
            }""")
            assert result == 3, result
            context.set_offline(False)
            wait_for(page, 'navigator.onLine')
            page.evaluate('window.SHSync.processQueue()')
            wait_for(page, "async () => !(await db.getAll(db.STORE_NAMES.syncQueue)).length")
            assert Invoice.objects.count() == 2
            assert Stock.objects.get(warehouse=warehouse, variant=variant).quantity == 3
            print('PASS: actual invoice form saves offline and creates its server invoice on reconnect', flush=True)
            # Actual form capture while offline, including bulk transfers.
            page.goto(base + '/inventory/movements/transfer/', wait_until='networkidle')
            wait_for(page, 'window.SHOffline && window.SHSync')
            page.wait_for_timeout(500)
            context.set_offline(True)
            # Re-create fixture after navigation; no test-only state survives reload.
            data = dict(variant=variant.pk, warehouse=warehouse.pk, target=target.pk)
            result = page.evaluate("""async (f) => {
                const db=await import('/static/js/pwa/db.js');
                const form=document.getElementById('bulk-transfer-form');
                form.elements.from_warehouse.value=f.warehouse;
                form.elements.to_warehouse.value=f.target;
                form.elements['items-0-variant'].value=f.variant;
                form.elements['items-0-quantity'].value=2;
                await window.SHOffline.queueFormSubmission(form);
                return {source:(await db.getRecord(db.STORE_NAMES.stock,`${f.warehouse}:${f.variant}`)).quantity,
                        target:(await db.getRecord(db.STORE_NAMES.stock,`${f.target}:${f.variant}`)).quantity};
            }""", data)
            assert result == dict(source=1, target=2), result
            # Reload a cached authenticated form with the network disabled.
            page.reload(wait_until='domcontentloaded')
            assert page.locator('#bulk-transfer-form').count() == 1
            context.set_offline(False)
            wait_for(page, 'navigator.onLine')
            page.evaluate('window.SHSync.processQueue()')
            wait_for(page, "async () => { const db=await import('/static/js/pwa/db.js'); return !(await db.getAll(db.STORE_NAMES.syncQueue)).length; }")
            assert Stock.objects.get(warehouse=warehouse, variant=variant).quantity == 1
            assert Stock.objects.get(warehouse=target, variant=variant).quantity == 2
            page.goto(base + '/inventory/stock/', wait_until='networkidle')
            context.set_offline(True)
            page.evaluate('window.SHOfflineLists.render()')
            wait_for(page, "document.querySelector('.stock-table-wrap [data-offline-row] td:nth-child(5)')?.textContent === '1'")
            local_rows = page.locator('.stock-table-wrap [data-offline-row]')
            assert local_rows.count() == 2
            cells = page.evaluate("Array.from(document.querySelectorAll('.stock-table-wrap [data-offline-row]'), row => Array.from(row.cells, cell => cell.textContent))")
            assert sorted(row[4] for row in cells) == ['1', '2'], cells
            context.set_offline(False)
            page.evaluate('window.SHOfflineLists.render()')
            assert page.locator('.stock-table-wrap tbody tr').count() == 2
            assert not errors, errors
            print('PASS: offline bulk form, cached reload, reconnect and server balances', flush=True)
            review_representative(browser, base)


def review_representative(browser, base):
    from django.test import Client
    from accounts.models import User
    from customers.models import Customer
    from products.models import Product, ProductVariant
    from inventory.models import Stock, StockBatch, Warehouse
    from purchases.models import Supplier
    from purchases.services import create_purchase_order, receive_purchase_order_items
    from orders.models import Order
    rep = User.objects.create_user(username='pwa-negative-rep', role='sales')
    customer = Customer.objects.create(name='Negative rep customer', created_by=rep)
    client = Client()
    client.force_login(rep)
    context = browser.new_context()
    context.add_cookies([dict(name='sessionid', value=client.cookies['sessionid'].value, url=base)])
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(base + '/orders/create/', wait_until='networkidle')
    wait_for(page, 'window.SHOffline && window.SHSync')
    page.evaluate("async () => { window.db=await import('/static/js/pwa/db.js'); await window.SHSync.bootstrapNow(); }")
    wait_for(page, "async () => !!await db.getMetadata('last_bootstrap_at')")
    warehouse = Warehouse.objects.get(assigned_user=rep, warehouse_type='representative')
    existing = ProductVariant.objects.get(variant_sku='PWA-V')
    page.goto(base + '/products/representative/create/', wait_until='networkidle')
    wait_for(page, 'window.SHOffline && window.SHSync')
    context.set_offline(True)
    local = page.evaluate("""async () => {
        const form=document.querySelector('form:has([name="sku"])');
        for (const [key,value] of Object.entries({name:'Offline rep product',sku:'REP-PWA-NEW',retail_price:'30',wholesale_price:'25',cost_price:'10'})) form.elements[key].value=value;
        await window.SHOffline.queueFormSubmission(form);
        const db=await import('/static/js/pwa/db.js');
        const product=(await db.searchProducts('REP-PWA-NEW'))[0];
        const variant=(await db.variantsForProduct(product.id))[0];
        return {product,variant};
    }""")
    assert local['product']['id'] and local['variant']['id']
    assert local['variant']['product_local_uuid'] == local['product']['id']
    page.goto(base + '/orders/create/', wait_until='domcontentloaded')
    wait_for(page, 'window.SHOffline && window.SHSync')
    fixture = dict(local=local, warehouse=warehouse.pk, customer=customer.pk, existing=existing.pk)
    result = page.evaluate("""async (f) => {
        const db=await import('/static/js/pwa/db.js');
        const form=document.getElementById('order-form');
        const warehouses=await db.stockForVariant(f.local.variant.id);
        if (warehouses[0]?.quantity !== 0) throw new Error('New product must start at zero');
        form.elements.customer.value=f.customer;
        form.elements.warehouse.value=f.warehouse;
        form.elements.payment_method.value='credit';
        form.elements.items_json.value=JSON.stringify([
            {variant_id:f.local.variant.id,warehouse_id:f.warehouse,quantity:10,unit_price:'30'},
            {variant_id:f.existing,warehouse_id:f.warehouse,quantity:3,unit_price:'30'}]);
        await window.SHOffline.queueFormSubmission(form,form.querySelector('[name="action"][value="confirm"]'));
        return {quantity:(await db.getRecord(db.STORE_NAMES.stock,`${f.warehouse}:${f.local.variant.id}`)).quantity,
                queue:(await db.getAll(db.STORE_NAMES.syncQueue)).length};
    }""",fixture)
    assert result == dict(quantity=-10,queue=2), result
    # Lose both acknowledgements to exercise partially synchronized aliases.
    page.evaluate("""() => {
        const original=window.fetch;
        let dropped=false;
        let droppedSale=false;
        window.fetch=async (...args) => {
            const response=await original(...args);
            if (!dropped && String(args[0]).includes('/api/sync/products/')) {
                dropped=true;
                throw new TypeError('Lost product acknowledgement');
            }
            if (!droppedSale && String(args[0]).includes('/api/sync/sales/')) {
                droppedSale=true;
                throw new TypeError('Lost sale acknowledgement');
            }
            return response;
        };
    }""")
    context.set_offline(False)
    wait_for(page,'navigator.onLine')
    page.evaluate('window.SHSync.processQueue()')
    wait_for(page,"async () => {const db=await import('/static/js/pwa/db.js'); return (await db.getAll(db.STORE_NAMES.syncQueue)).some(x=>x.status==='failed');}")
    assert Product.objects.filter(sku='REP-PWA-NEW').count() == 1
    assert not Order.objects.filter(created_by=rep).exists()
    page.evaluate("""async () => {
        const db=await import('/static/js/pwa/db.js');
        for (const row of await db.getAll(db.STORE_NAMES.syncQueue)) if (row.status==='failed') await db.putRecord(db.STORE_NAMES.syncQueue,{...row,status:'pending',next_attempt_at:db.nowIso()});
        await window.SHSync.processQueue();
    }""")
    wait_for(page,"async () => {const db=await import('/static/js/pwa/db.js');return (await db.getAll(db.STORE_NAMES.syncQueue)).some(x=>x.entity_name==='sales' && x.status==='failed');}")
    result = page.evaluate("""async (f) => {
        const db=await import('/static/js/pwa/db.js');
        const product=(await db.searchProducts('REP-PWA-NEW'))[0];
        const variants=await db.variantsForProduct(product.id);
        return {variants:variants.length, quantity:(await db.stockForVariant(f.local.variant.id))[0].quantity,
                price:await db.priceForVariant(f.local.variant.id)};
    }""",fixture)
    assert result == dict(variants=1,quantity=-10,price='30'), result
    page.evaluate("""async () => {
        const db=await import('/static/js/pwa/db.js');
        for (const row of await db.getAll(db.STORE_NAMES.syncQueue)) if (row.status==='failed') await db.putRecord(db.STORE_NAMES.syncQueue,{...row,status:'pending',next_attempt_at:db.nowIso()});
        await window.SHSync.processQueue();
    }""")
    wait_for(page,"async () => {const db=await import('/static/js/pwa/db.js');return !(await db.getAll(db.STORE_NAMES.syncQueue)).length;}")
    variant = ProductVariant.objects.get(product__sku='REP-PWA-NEW')
    assert Stock.objects.get(warehouse=warehouse,variant=variant).quantity == -10
    assert Stock.objects.get(warehouse=warehouse,variant=existing).quantity == -3
    assert Order.objects.filter(created_by=rep).count() == 1
    assert Product.objects.filter(sku='REP-PWA-NEW').count() == 1
    manager=User.objects.get(username='pwa-test')
    supplier=Supplier.objects.create(name='Negative rep supplier')
    purchase=create_purchase_order(supplier=supplier,items=[{'product_variant':variant,'quantity':16,'unit_cost':12}],user=manager)
    item=purchase.items.get()
    for quantity, expected in [(6,-4),(10,6)]:
        receive_purchase_order_items(purchase_order=purchase,warehouse=warehouse,received_items={item.pk:quantity},user=manager)
        assert Stock.objects.get(warehouse=warehouse,variant=variant).quantity == expected
    assert sum(StockBatch.objects.filter(warehouse=warehouse,variant=variant).values_list('remaining_quantity',flat=True)) == 6
    page.evaluate('window.SHSync.bootstrapNow()')
    context.set_offline(True)
    result=page.evaluate("""async (f) => {
        const db=await import('/static/js/pwa/db.js');
        return (await db.stockForVariant(f.variant)).find(row=>row.warehouse_id===f.warehouse).quantity;
    }""",dict(variant=variant.pk,warehouse=warehouse.pk))
    assert result == 6, result
    assert not errors, errors
    context.close()
    print('PASS: representative new offline product, existing product negative sale, ordered dependency/retry and purchase settlement',flush=True)


if __name__ == '__main__':
    main()
