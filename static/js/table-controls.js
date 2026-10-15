// Shared table preferences and live GET filters. Both use delegation so workspace tabs work.
(() => {
    const storagePrefix = 'sh-table-columns-v1:';
    let filterTimer;

    function setupTables() {
        document.querySelectorAll('[data-page-content] table').forEach((table, tableIndex) => {
            if (table.dataset.columnControlsReady) return;
            const headingRow = table.tHead?.rows[0] || table.rows[0];
            const headers = headingRow ? [...headingRow.children].filter(cell => cell.matches('th, td')) : [];
            if (headers.length < 2) return;
            table.dataset.columnControlsReady = '1';
            const key = storagePrefix + location.pathname + ':' + tableIndex + ':' + headers.map(h => h.textContent.trim()).join('|');
            let hidden = [];
            try { hidden = JSON.parse(localStorage.getItem(key) || '[]'); } catch (_) { hidden = []; }
            if (!Array.isArray(hidden)) hidden = [];

            const control = document.createElement('details');
            control.className = 'table-column-control no-print';
            const summary = document.createElement('summary');
            summary.textContent = 'الأعمدة';
            summary.setAttribute('aria-label', 'اختيار أعمدة الجدول');
            control.append(summary);
            const choices = document.createElement('div');
            choices.className = 'table-column-options';
            control.append(choices);

            function apply() {
                const visible = headers.flatMap((header, index) => Array(Number(header.dataset.originalColspan || header.colSpan || 1)).fill(!hidden.includes(index)));
                [...table.querySelectorAll('tr')].filter(row => row.closest('table') === table).forEach(row => {
                    let index = 0;
                    [...row.children].forEach(cell => {
                        if (!cell.matches('th, td')) return;
                        const span = Number(cell.dataset.originalColspan || cell.colSpan || 1);
                        cell.dataset.originalColspan = span;
                        const count = visible.slice(index, index + span).filter(Boolean).length;
                        cell.hidden = count === 0;
                        if (count) cell.colSpan = count;
                        index += span;
                    });
                });
            }

            headers.forEach((header, index) => {
                const label = document.createElement('label');
                const checkbox = document.createElement('input');
                checkbox.type = 'checkbox';
                checkbox.checked = !hidden.includes(index);
                checkbox.addEventListener('change', () => {
                    if (!checkbox.checked && headers.length - hidden.length <= 1) {
                        checkbox.checked = true;
                        return;
                    }
                    hidden = checkbox.checked ? hidden.filter(value => value !== index) : [...hidden, index];
                    try { localStorage.setItem(key, JSON.stringify(hidden)); } catch (_) { /* private browsing */ }
                    apply();
                });
                label.append(checkbox, document.createTextNode(header.textContent.trim() || `عمود ${index + 1}`));
                choices.append(label);
            });
            const wrap = table.closest('.table-wrap, .stock-table-wrap, .cash-table-wrap, .items-table-wrap');
            (wrap || table).before(control);
            apply();
        });
    }

    function filterUrl(form) {
        const url = new URL(form.action || location.href, location.href);
        url.search = new URLSearchParams(new FormData(form)).toString();
        return url.pathname + url.search;
    }

    async function updateFilter(form, field) {
        const url = filterUrl(form);
        if (url === location.pathname + location.search) return;
        const name = field?.name;
        const start = field?.selectionStart;
        const end = field?.selectionEnd;
        if (window.SHWorkspace?.navigateFilter) {
            await window.SHWorkspace.navigateFilter(url);
        } else {
            location.assign(url);
            return;
        }
        if (name && field?.matches('input[type="search"], input[type="text"]')) {
            const next = [...document.querySelectorAll('[data-live-filter] [name]')].find(input => input.name === name);
            next?.focus();
            try { next?.setSelectionRange(start, end); } catch (_) { /* unsupported input */ }
        }
    }

    document.addEventListener('submit', event => {
        const form = event.target.closest('form[data-live-filter]');
        if (!form) return;
        event.preventDefault();
        clearTimeout(filterTimer);
        updateFilter(form).catch(() => location.assign(filterUrl(form)));
    });
    document.addEventListener('input', event => {
        const field = event.target;
        const form = field.closest('form[data-live-filter]');
        if (!form || !field.matches('input[type="search"], input[name="q"]')) return;
        clearTimeout(filterTimer);
        filterTimer = setTimeout(() => updateFilter(form, field).catch(() => location.assign(filterUrl(form))), 350);
    });
    document.addEventListener('change', event => {
        const field = event.target;
        const form = field.closest('form[data-live-filter]');
        if (!form || field.matches('input[name="q"]')) return;
        const period = field.closest('[data-period-filter]');
        if (period && (field.name === 'period' && field.value === 'custom' || field.name.startsWith('datetime_'))) {
            if (field.name === 'period') return;
            const from = period.querySelector('[name="datetime_from"]')?.value;
            const to = period.querySelector('[name="datetime_to"]')?.value;
            if (!from && !to) return;
        }
        clearTimeout(filterTimer);
        updateFilter(form).catch(() => location.assign(filterUrl(form)));
    });
    document.addEventListener('click', event => {
        document.querySelectorAll('.table-column-control[open]').forEach(control => {
            if (!control.contains(event.target)) control.open = false;
        });
    });
    document.addEventListener('DOMContentLoaded', setupTables);
    document.addEventListener('sh:page-loaded', setupTables);
})();
