import {getAll, getMetadata, calculateOrderTotals, STORE_NAMES} from './db.js';

const node = (tag, text) => { const el = document.createElement(tag); el.textContent = String(text ?? '-'); return el; };
const id = row => String(row.server_id || row.id);
const money = value => Number(value || 0).toFixed(2);
let revision = 0;
function link(title, url) { const el = node('a', title); el.href = url; return el; }
function table(headers, rows) {
    const wrap = document.createElement('div'); wrap.className = 'table-wrap';
    const el = document.createElement('table'); const head = el.createTHead().insertRow();
    headers.forEach(text => head.append(node('th', text)));
    const body = el.createTBody();
    rows.forEach(values => {const row = body.insertRow(); values.forEach(value => {
        const cell = row.insertCell(); if (value instanceof Node) cell.append(value); else cell.textContent = String(value ?? '-');
    });});
    if (!rows.length) { const cell = body.insertRow().insertCell(); cell.colSpan = headers.length; cell.textContent = 'لا توجد بيانات محلية مطابقة'; }
    wrap.append(el); return wrap;
}
function normalizeOrder(row) {
    const data = row.order || row.payload?.order || row;
    const items = row.payload?.items || row.items || [];
    return {...data, id: id(row), items, invoice_id: row.invoice_id,
        total: data.total ?? calculateOrderTotals({...data, items}).total,
        local: row.sync_status !== 'synced', document_type: data.document_type || 'sale'};
}
async function render() {
    const current = ++revision;
    const container = document.querySelector('[data-page-content]');
    if (!container || (navigator.onLine && !container.hasAttribute('data-pwa-local'))) return;
    const path = location.pathname;
    const productList = path === '/products/';
    const orderList = ['/orders/', '/orders/quotes/', '/invoices/'].includes(path);
    const customerList = ['/customers/', '/customers/list/'].includes(path);
    const detail = path.match(/^\/(products|orders|invoices|customers(?:\/simple)?)\/(\d+)\/$/);
    if (!productList && !orderList && !customerList && !detail) return;
    const [products, rawOrders, customers, variants, downloaded, allowed] = await Promise.all([
        getAll(STORE_NAMES.products), getAll(STORE_NAMES.sales), getAll(STORE_NAMES.customers),
        getAll(STORE_NAMES.productVariants), getMetadata('last_bootstrap_at'), getMetadata('offline_details'),
    ]);
    if (current !== revision || !container.isConnected || !downloaded) return;
    const orders = rawOrders.filter(row => row.document_type || row.order || row.payload?.order).map(normalizeOrder);
    const customerName = order => customers.find(row => id(row) === String(order.customer_id || order.customer_server_id)
        || row.local_uuid === order.customer_local_uuid)?.name || 'عميل نقدي';
    const params = new URLSearchParams(location.search);
    const q = (params.get('q') || '').trim().toLocaleLowerCase();
    const matches = row => !q || JSON.stringify(row).toLocaleLowerCase().includes(q);
    const title = node('h1', productList ? 'المنتجات المحلية' : customerList ? 'العملاء المحليون' : path.includes('quotes') ? 'عروض الأسعار المحلية' : 'الفواتير المحلية');
    const children = [title, node('p', `بيانات محفوظة على هذا الجهاز — آخر تحميل: ${new Date(downloaded).toLocaleString('ar-EG')}`)];
    if (productList) {
        children.push(link('إضافة منتج', '/products/create/'));
        children.push(table(['المنتج', 'الكود', 'سعر الجملة', 'سعر القطاعي'], products.filter(matches).map(row => [
            row.server_id ? link(row.name, `/products/${row.server_id}/`) : row.name, row.sku, row.wholesale_price, row.retail_price,
        ])));
    } else if (orderList) {
        const quote = path.includes('quotes');
        children.push(link(quote ? 'عرض سعر جديد' : 'فاتورة جديدة', `/orders/create/${quote ? '?document=quote' : ''}`));
        children.push(table(['المستند', 'العميل', 'الإجمالي', 'المدفوع', 'المتبقي', 'الحالة'], orders
            .filter(row => (row.document_type === 'quote') === quote && matches(row))
            .filter(row => !params.get('status') || row.status === params.get('status'))
            .filter(row => path !== '/invoices/' || row.invoice_id || row.local)
            .map(row => [
                /^\d+$/.test(row.id) ? link(row.order_number || row.id, `/orders/${row.id}/`) : 'محلي قيد المزامنة',
                customerName(row), money(row.total), money(row.paid_amount), money(row.remaining_amount ?? Math.max(0, row.total - Number(row.paid_amount || 0))),
                row.local ? 'قيد المزامنة' : row.status,
            ])));
    } else if (customerList) {
        children.push(table(['العميل', 'الهاتف', 'العنوان', 'الرصيد الافتتاحي'], customers.filter(matches).map(row => [
            row.server_id ? link(row.name, `/customers/simple/${row.server_id}/`) : row.name, row.phone, row.address, row.opening_balance,
        ])));
    } else {
        if (!allowed?.includes(path)) return;
        const [, entity, key] = detail;
        if (entity === 'products') {
            const product = products.find(row => id(row) === key); if (!product) return;
            title.textContent = product.name;
            children.push(node('p', `الكود: ${product.sku}`), table(['الصنف', 'اللون', 'المقاس', 'سعر البيع'],
                variants.filter(row => String(row.product_id) === key).map(row => [row.variant_sku, row.color, row.size, row.retail_price])));
        } else if (entity.startsWith('customers')) {
            const customer = customers.find(row => id(row) === key); if (!customer) return;
            title.textContent = customer.name;
            children.push(node('p', customer.phone), node('p', customer.address), link('كشف الحساب', `/finance/statements/customer/?customer=${key}`));
        } else {
            const order = orders.find(row => entity === 'invoices' ? String(row.invoice_id) === key : row.id === key); if (!order) return;
            title.textContent = `${order.document_type === 'quote' ? 'عرض سعر' : 'فاتورة'} ${order.order_number || key}`;
            children.push(node('p', customerName(order)), node('p', `الإجمالي: ${money(order.total)} — المدفوع: ${money(order.paid_amount)}`));
            children.push(table(['الصنف', 'الكمية', 'سعر الوحدة', 'الإجمالي'], order.items.map(item => [
                item.product_name || variants.find(row => id(row) === String(item.variant_id))?.product_name,
                item.quantity, item.unit_price, item.total ?? Number(item.quantity) * Number(item.unit_price),
            ])));
        }
    }
    container.dataset.localDataView = '1';
    container.replaceChildren(...children);
}
const schedule = () => render().catch(error => console.warn('Local page unavailable', error));
document.addEventListener('sh:page-loaded', schedule);
window.addEventListener('offline', schedule);
window.addEventListener('sh-sync-status', schedule);
window.addEventListener('DOMContentLoaded', schedule);
schedule();
