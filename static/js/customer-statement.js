import { getAll, STORE_NAMES } from './pwa/db.js';
import { localCustomerStatement } from './pwa/customer-ledger.js';

function element(tag, text, className = '') {
    const node = document.createElement(tag);
    node.textContent = text;
    node.className = className;
    return node;
}

function initializeStatement() {
    const picker = document.querySelector('[data-customer-picker]');
    if (!picker || picker.dataset.statementBound) return;
    picker.dataset.statementBound = '1';
    const search = picker.querySelector('#statement-customer-search');
    const customerId = picker.querySelector('#statement-customer-id');
    const results = picker.querySelector('#statement-customer-results');
    const host = document.querySelector('[data-offline-statement]');
    let timer, controller;
    let offlineMode = !navigator.onLine;
    let renderVersion = 0;

    async function checkConnection() {
        if (!navigator.onLine) return false;
        const abort = new AbortController();
        const timeout = setTimeout(() => abort.abort(), 4000);
        try {
            return (await fetch('/api/sync/ping/', { cache: 'no-store', signal: abort.signal })).ok;
        } catch { return false; }
        finally { clearTimeout(timeout); }
    }

    function closeResults() {
        results.hidden = true;
        results.replaceChildren();
        search.setAttribute('aria-expanded', 'false');
    }
    async function localCustomers(query) {
        const records = await getAll(STORE_NAMES.customers);
        return records.filter(customer => `${customer.name} ${customer.phone || ''}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()))
            .slice(0, 30).map(customer => ({ ...customer, id: customer.server_id || customer.id }));
    }
    function showMessage(message) {
        results.replaceChildren(element('p', message));
        results.hidden = false;
        search.setAttribute('aria-expanded', 'true');
    }
    async function showLocalStatement() {
        const version = ++renderVersion;
        const selectedId = customerId.value;
        document.querySelector('[data-server-statement]').hidden = true;
        host.hidden = false;
        try {
            const [customers, sales, payments] = await Promise.all([
                getAll(STORE_NAMES.customers), getAll(STORE_NAMES.sales), getAll(STORE_NAMES.cashTransactions),
            ]);
            const customer = customers.find(item => String(item.server_id || item.id) === String(customerId.value));
            if (!customer) throw new Error('اختر عميلًا من البيانات المنزلة لهذا الحساب.');
            const statement = localCustomerStatement(customer, sales, payments);
            if (version !== renderVersion || selectedId !== customerId.value || !picker.isConnected) return;
            const content = document.createElement('div');
            search.value = customer.name;
            content.append(element('h2', customer.name), element('p',
                `كشف محفوظ بتاريخ ${new Date(statement.downloaded_at).toLocaleString('ar-EG')}، ويشمل البيع والقبض المحليين منذ آخر تنزيل. الحركات المحلية تنتظر تأكيد المزامنة.`));
            const balance = element('section', '', 'card');
            balance.append(element('span', 'الرصيد الحالي'), element('strong', statement.balance, 'statement-number'));
            balance.dataset.offlineBalance = statement.balance;
            content.append(balance);
            const wrap = element('div', '', 'table-wrap');
            const table = document.createElement('table');
            const head = document.createElement('thead');
            const heading = document.createElement('tr');
            ['التاريخ', 'نوع الحركة', 'عليه', 'له', 'الرصيد'].forEach(label => heading.append(element('th', label)));
            head.append(heading);
            const body = document.createElement('tbody');
            statement.entries.forEach(entry => {
                const row = document.createElement('tr');
                [entry.date, entry.type, entry.debit, entry.credit, entry.balance].forEach(value => row.append(element('td', value)));
                if (entry.local) row.dataset.localStatementEntry = '1';
                body.append(row);
            });
            table.append(head, body);
            wrap.append(table);
            content.append(wrap);
            host.replaceChildren(content);
        } catch (error) {
            if (version === renderVersion) host.replaceChildren(element('p', error.message, 'card'));
        }
    }
    picker.addEventListener('submit', event => {
        if (!offlineMode && navigator.onLine) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        showLocalStatement();
    });
    search.addEventListener('input', () => {
        clearTimeout(timer);
        controller?.abort();
        customerId.value = '';
        const query = search.value.trim();
        if (query.length < 2) return closeResults();
        timer = setTimeout(async () => {
            controller = new AbortController();
            try {
                let customers;
                if (offlineMode || !navigator.onLine) customers = await localCustomers(query);
                else {
                    try {
                        const url = new URL(picker.dataset.searchUrl, location.href);
                        url.searchParams.set('q', query);
                        const response = await fetch(url, { signal: controller.signal });
                        if (!response.ok) throw new Error('تعذر البحث');
                        customers = (await response.json()).data || [];
                    } catch (error) {
                        if (error.name === 'AbortError') return;
                        offlineMode = true;
                        customers = await localCustomers(query);
                    }
                }
                if (search.value.trim() !== query) return;
                if (!customers.length) return showMessage('لا توجد نتائج مطابقة.');
                results.replaceChildren();
                customers.forEach(customer => {
                    const option = element('button', '', '');
                    option.type = 'button';
                    option.append(element('strong', customer.name), element('small', customer.phone || `#${customer.id}`));
                    option.addEventListener('click', () => {
                        search.value = customer.name;
                        customerId.value = customer.id;
                        closeResults();
                        picker.requestSubmit();
                    });
                    results.append(option);
                });
                results.hidden = false;
                search.setAttribute('aria-expanded', 'true');
            } catch (error) { showMessage(error.message); }
        }, 250);
    });
    search.addEventListener('keydown', event => {
        if (event.key === 'Escape') closeResults();
        if (event.key === 'Enter' && !results.hidden && results.querySelector('button')) {
            event.preventDefault();
            results.querySelector('button').click();
        }
    });
    customerId.addEventListener('input', closeResults);
    document.addEventListener('click', event => { if (!picker.contains(event.target)) closeResults(); });
    const params = new URLSearchParams(location.search);
    if (offlineMode) {
        customerId.value = params.get('customer') || '';
        if (customerId.value) showLocalStatement();
    }
    else checkConnection().then(reachable => {
        if (reachable || !picker.isConnected) return;
        offlineMode = true;
        customerId.value = params.get('customer') || customerId.value;
        if (customerId.value) showLocalStatement();
    });
    window.addEventListener('offline', () => {
        offlineMode = true;
        if (picker.isConnected && customerId.value) showLocalStatement();
    });
    window.addEventListener('online', () => { offlineMode = false; });
    window.addEventListener('sh-sync-status', () => {
        if (picker.isConnected && !host.hidden && customerId.value) showLocalStatement();
    });
}

initializeStatement();
document.addEventListener('sh:page-loaded', initializeStatement);
