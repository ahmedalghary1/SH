import { getAll, putRecord, STORE_NAMES, nowIso } from './db.js';
import { getOfflineScope } from './identity.js';
import { processQueue } from './sync-engine.js';

const names = { sales: 'فاتورة', customers: 'عميل', cash: 'حركة مالية', stock: 'حركة مخزون', products: 'منتج', purchases: 'مشتريات', returns: 'مرتجع', driver_actions: 'عملية مندوب' };
const statuses = { pending: 'بانتظار المزامنة', failed: 'تعذرت المزامنة مؤقتًا', conflict: 'تحتاج إلى مراجعة' };
let dialog;

function node(tag, value, className = '') {
    const element = document.createElement(tag);
    element.textContent = value;
    element.className = className;
    return element;
}

async function items() {
    return getOfflineScope() ? (await getAll(STORE_NAMES.syncQueue)).sort((a, b) => String(a.timestamp).localeCompare(String(b.timestamp))) : [];
}

async function refresh() {
    try {
        const queued = await items();
        const label = document.querySelector('[data-pwa-sync-label]');
        if (label) label.textContent = navigator.onLine ? (queued.length ? `مزامنة (${queued.length})` : 'مزامنة') : `بدون اتصال${queued.length ? ` (${queued.length})` : ''}`;
        const details = document.querySelector('[data-pwa-queue]');
        if (details) details.hidden = queued.length === 0;
        if (dialog?.open) render(queued);
    } catch {
        const label = document.querySelector('[data-pwa-sync-label]');
        if (label) label.textContent = 'التخزين المحلي غير متاح';
    }
}

function createDialog() {
    dialog = document.createElement('dialog');
    dialog.className = 'sync-queue-panel';
    dialog.setAttribute('aria-labelledby', 'sync-queue-title');
    const title = node('h2', 'العمليات المحفوظة على هذا الجهاز');
    title.id = 'sync-queue-title';
    const info = node('p', 'لم تصبح العملية نهائية حتى يقبلها السيرفر. احتفظ بهذه البيانات وراجع أي مشكلة قبل إعادة إدخالها.', 'muted');
    const list = node('div', '');
    list.dataset.queueRows = '';
    const actions = node('div', '', 'form-actions');
    const retry = node('button', 'إعادة محاولة المزامنة', 'btn btn-primary');
    retry.type = 'button';
    retry.addEventListener('click', async () => {
        retry.disabled = true;
        try {
            // Keep the same idempotency key. Permanent conflicts need review.
            for (const item of await items()) {
                if (item.status === 'failed') await putRecord(STORE_NAMES.syncQueue, { ...item, status: 'pending', next_attempt_at: nowIso() });
            }
            await processQueue();
            await refresh();
        } finally { retry.disabled = false; }
    });
    const download = node('button', 'تنزيل نسخة من العمليات المعلقة', 'btn btn-light');
    download.type = 'button';
    download.addEventListener('click', async () => {
        const content = JSON.stringify({ scope: getOfflineScope(), exported_at: nowIso(), operations: await items() }, (key, value) => ['csrfmiddlewaretoken', '_submission_token'].includes(key) ? undefined : value, 2);
        const url = URL.createObjectURL(new Blob([content], { type: 'application/json' }));
        const link = node('a', '');
        link.href = url;
        link.download = `sh-pending-${new Date().toISOString().slice(0, 10)}.json`;
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
    const close = node('button', 'إغلاق', 'btn btn-light');
    close.type = 'button';
    close.addEventListener('click', () => dialog.close());
    actions.append(retry, download, close);
    dialog.append(title, info, list, actions);
    document.body.append(dialog);
}

function render(queued) {
    const list = dialog.querySelector('[data-queue-rows]');
    list.replaceChildren();
    if (!queued.length) list.append(node('p', 'تمت مزامنة كل العمليات.'));
    for (const item of queued) {
        const row = node('section', '', 'sync-queue-row');
        row.append(node('strong', `${names[item.entity_name] || 'عملية'} — ${statuses[item.status] || item.status}`));
        row.append(node('p', new Date(item.timestamp).toLocaleString('ar-EG'), 'muted'));
        if (item.error) row.append(node('p', item.error, 'form-errors'));
        row.append(node('small', `رقم العملية: ${item.local_uuid}`));
        list.append(row);
    }
}

document.addEventListener('click', async (event) => {
    if (!event.target.closest('[data-pwa-queue]')) return;
    if (!dialog) createDialog();
    render(await items());
    if (!dialog.open) dialog.showModal();
});
window.addEventListener('sh-sync-status', refresh);
window.addEventListener('online', refresh);
window.addEventListener('offline', refresh);
document.addEventListener('sh:page-loaded', refresh);
refresh();
