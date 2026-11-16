// Shared by server-rendered lists, workspace tabs and offline-generated rows.
(() => {
    const interactive = 'a, button, input, select, textarea, label, summary, [role="button"], [role="checkbox"], [contenteditable]:not([contenteditable="false"]), [data-no-row-navigation]';
    const detailPath = /^\/(?:products\/\d+|orders\/\d+|invoices\/\d+|returns\/\d+|customers\/(?:simple\/)?\d+(?:\/crm)?|purchases\/(?:orders|suppliers(?:\/simple)?)\/\d+|finance\/accounts\/\d+|inventory\/movements\/products\/\d+)\/$/;

    function eligible(link) {
        const raw = link.getAttribute('href');
        if (!raw || raw.startsWith('#') || link.hasAttribute('download') || link.matches('[data-no-row-navigation]')) return false;
        const url = new URL(raw, location.href);
        return url.origin === location.origin && ['http:', 'https:'].includes(url.protocol)
            && !/\/(?:delete|edit|update|cancel|deactivate|approve|complete|reject|pay|receive|export[^/]*|print|download)(?:\/|$)/i.test(url.pathname);
    }

    function destination(row) {
        if (row.matches('[data-no-row-navigation], .table-total-row') || row.closest('thead, tfoot')) return null;
        const links = [...row.querySelectorAll('a[href]')].filter(link => link.closest('tr') === row && eligible(link));
        if (row.dataset.rowLink && !row.dataset.autoRowLink) {
            return links.find(link => new URL(link.href, location.href).href === new URL(row.dataset.rowLink, location.href).href) || null;
        }
        return links.find(link => link.hasAttribute('data-row-target'))
            || links.find(link => /^(عرض|التفاصيل|تفاصيل|فتح|عرض التفاصيل|ملف العميل|كشف الحساب)$/.test(link.textContent.trim()))
            || links.find(link => detailPath.test(new URL(link.href, location.href).pathname)) || null;
    }

    function setup() {
        document.querySelectorAll('[data-page-content] table tr').forEach(row => {
            const link = destination(row);
            if (link) {
                if (!row.hasAttribute('data-row-link')) row.dataset.autoRowLink = '1';
                row.dataset.rowLink = link.getAttribute('href');
                row.tabIndex = 0;
                row.setAttribute('aria-label', `فتح التفاصيل: ${row.cells[0]?.textContent.trim() || link.textContent.trim()}`);
            } else if (row.dataset.autoRowLink) {
                delete row.dataset.rowLink;
                delete row.dataset.autoRowLink;
                row.removeAttribute('tabindex');
                row.removeAttribute('aria-label');
            }
        });
    }

    document.addEventListener('click', event => {
        if (event.defaultPrevented || event.button !== 0 || event.target.closest(interactive)) return;
        const row = event.target.closest('tr');
        if (!row || !row.closest('[data-page-content]') || window.getSelection()?.toString()) return;
        const link = destination(row);
        if (!link) return;
        if (event.ctrlKey || event.metaKey || event.shiftKey) window.open(link.href, '_blank', 'noopener');
        else link.click(); // Preserve the existing workspace and offline navigation.
    });
    document.addEventListener('keydown', event => {
        if (event.defaultPrevented || event.repeat || !['Enter', ' '].includes(event.key) || !event.target.matches('tr[data-row-link]')) return;
        const link = destination(event.target);
        if (!link) return;
        event.preventDefault();
        link.click();
    });
    let scheduled = false;
    function schedule() {
        if (scheduled) return;
        scheduled = true;
        queueMicrotask(() => { scheduled = false; setup(); });
    }
    new MutationObserver(schedule).observe(document.body, {childList: true, subtree: true});
    document.addEventListener('DOMContentLoaded', setup);
    document.addEventListener('sh:page-loaded', setup);
    setup();
})();
