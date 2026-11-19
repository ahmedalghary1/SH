// Shared table sorting, column preferences and live GET filters.
(() => {
    const storagePrefix = 'sh-table-columns-v1:';
    let filterTimer;
    const tables = new WeakMap();
    const collator = new Intl.Collator('ar', {numeric: true, sensitivity: 'base'});
    const months = 'يناير فبراير مارس أبريل مايو يونيو يوليو أغسطس سبتمبر أكتوبر نوفمبر ديسمبر'.split(' ');
    const content = document.querySelector('[data-page-content], body #content-main');

    function spanOf(cell) {
        return Number(cell.dataset.originalColspan || cell.colSpan);
    }

    function isRecord(row) {
        return row.cells.length && (row.cells[0].tagName === 'TD' || row.closest('table').tHead || row.rowIndex > 0)
            && !row.matches('.empty-row, .empty-form, .add-row, .table-total-row, .customers-total-row, [data-no-match]')
            && !(row.cells.length === 1 && spanOf(row.cells[0]) > 1);
    }

    function valueAt(row, column) {
        for (const cell of row.cells) {
            if (column < spanOf(cell)) {
                const input = cell.querySelector('select, input:not([type="hidden"]), textarea');
                const value = cell.dataset.sortValue ?? cell.querySelector('time[datetime]')?.dateTime
                    ?? (input?.type === 'checkbox' ? Number(input.checked) : input?.selectedOptions?.[0]?.text ?? input?.value)
                    ?? (cell.textContent.trim() || cell.querySelector('img')?.getAttribute('src') || '');
                return String(value).trim().replace(/[\u061c\u200e\u200f]/g, '').replace(/[٠-٩]/g, d => d.charCodeAt(0) - 1632)
                    .replace(/[۰-۹]/g, d => d.charCodeAt(0) - 1776);
            }
            column -= spanOf(cell);
        }
        return '';
    }

    function decimalKey(text) {
        const raw = text.replace(/\s*(?:ج\.?\s?م\.?|جنيه|EGP|[%٪])$/i, '').trim().replace(/^−/, '-');
        if (!/^[+-]?\d+(?:[٬٫,.]\d+)*$/.test(raw)) return null;
        const normalized = raw.replace(/٬/g, '').replace(/٫/g, '.');
        const decimal = /^[+-]?\d+,\d{1,2}$/.test(normalized) ? normalized.replace(',', '.') : normalized.replace(/,/g, '');
        const match = /^([+-]?)(\d+)(?:\.(\d+))?$/.exec(decimal);
        if (!match) return null;
        const integer = match[2].replace(/^0+(?=\d)/, '');
        const fraction = (match[3] || '').replace(/0+$/, '');
        return {negative: match[1] === '-' && (integer !== '0' || !!fraction), integer, fraction};
    }

    function compareDecimals(a, b) {
        if (a.negative !== b.negative) return a.negative ? -1 : 1;
        const magnitude = a.integer.length - b.integer.length
            || (a.integer < b.integer ? -1 : a.integer > b.integer ? 1 : 0)
            || (a.fraction < b.fraction ? -1 : a.fraction > b.fraction ? 1 : 0);
        return a.negative ? -magnitude : magnitude;
    }

    function dateKey(text) {
        const clock = /^(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([صم])?$/.exec(text);
        if (clock) {
            const hour = clock[4] ? +clock[1] % 12 + (clock[4] === 'م' ? 12 : 0) : +clock[1];
            return (hour * 60 + +clock[2]) * 60 + Number(clock[3] || 0);
        }
        if (/^\d{4}-\d{2}-\d{2}(?:[T ].+)?$/.test(text)) {
            const iso = text.replace(' ', 'T');
            const stamp = Date.parse(iso.length > 10 && !/(Z|[+-]\d\d:\d\d)$/i.test(iso) ? iso + 'Z' : iso);
            return Number.isFinite(stamp) ? stamp : null;
        }
        // Django also renders "مارس 5, 2026" and "5 مارس، 2026".
        const date = text.replace(/^[^،\d]+،\s*/, '').replace(/[،,]/g, ' ')
            .replace(/^(\S+)\s+(\d{1,2})\s+/, (prefix, word, day) => months.includes(word) ? day + ' ' + word + ' ' : prefix);
        const match = /^(\d{1,2})[\s/.-]+([^\s/.-]+)[\s/.-]+(\d{4})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([صم])?)?$/.exec(date);
        if (!match) return null;
        const month = Number(match[2]) || months.indexOf(match[2]) + 1;
        if (month < 1 || month > 12) return null;
        const hour = Number(match[4] || 0);
        return Date.UTC(+match[3], month - 1, +match[1], match[7] ? hour % 12 + (match[7] === 'م' ? 12 : 0) : hour,
            Number(match[5] || 0), Number(match[6] || 0));
    }

    function sortBody(body, state) {
        const rows = Array.from(body.rows);
        const entries = new Map();
        for (const row of rows.filter(isRecord)) {
            const text = valueAt(row, state.column);
            const blank = /^(?:[-–—]|\s)*$/.test(text);
            entries.set(row, {row, text, blank, number: blank ? null : decimalKey(text), date: blank ? null : dateKey(text)});
        }
        const ordered = Array.from(entries.values());
        const numeric = ordered.every(item => item.blank || item.number !== null);
        const dated = !numeric && ordered.every(item => item.blank || item.date !== null);
        ordered.sort((a, b) => {
            if (a.blank || b.blank) return Number(a.blank) - Number(b.blank);
            const comparison = numeric ? compareDecimals(a.number, b.number)
                : dated ? a.date - b.date : collator.compare(a.text, b.text);
            return state.ascending ? comparison : -comparison;
        });
        let next = 0;
        const result = rows.map(row => entries.has(row) ? ordered[next++].row : row);
        if (result.some((row, i) => row !== rows[i])) {
            const fragment = document.createDocumentFragment();
            result.forEach(row => fragment.append(row));
            body.append(fragment);
        }
    }

    function refresh(table, state) {
        let count = 0;
        for (const body of table.tBodies) {
            count += Array.from(body.rows).filter(isRecord).length;
            if (state.column !== null) sortBody(body, state);
        }
        if (state.count !== count) {
            state.badge.textContent = 'إجمالي العدد: ' + count.toLocaleString('en-US');
            state.count = count;
        }
    }

    function setupTable(table, tableIndex) {
        if (tables.has(table)) return;
        const headingRow = table.tHead?.rows[0] || table.rows[0];
        if (!headingRow?.querySelector('th:not([scope="row"])')) return;
        const headers = Array.from(headingRow.cells);
        const badge = document.createElement('div');
        badge.className = 'table-record-count number-value';
        const state = {column: null, badge};
        tables.set(table, state);
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
            Array.from(table.rows).forEach(row => {
                let index = 0;
                [...row.children].forEach(cell => {
                    if (!cell.matches('th, td')) return;
                    const span = Number(cell.dataset.originalColspan || cell.colSpan || 1);
                    if (span > 1) cell.dataset.originalColspan = span;
                    const count = visible.slice(index, index + span).filter(Boolean).length;
                    cell.hidden = count === 0;
                    if (count && cell.colSpan !== count) cell.colSpan = count;
                    index += span;
                });
            });
        }

        let column = 0;
        headers.forEach((header, index) => {
            const labelText = (header.querySelector('.text') || header).textContent.trim() || `عمود ${index + 1}`;
            const sortColumn = column;
            column += spanOf(header);
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'table-sort-button';
            button.setAttribute('aria-label', 'ترتيب حسب ' + labelText);
            if (!header.querySelector('input, button, a, select, label')) {
                while (header.firstChild) button.append(header.firstChild);
            }
            header.append(button);
            button.addEventListener('click', () => {
                state.ascending = state.column !== sortColumn || !state.ascending;
                state.column = sortColumn;
                headers.forEach(th => th.removeAttribute('aria-sort'));
                header.setAttribute('aria-sort', state.ascending ? 'ascending' : 'descending');
                for (const body of table.tBodies) sortBody(body, state);
            });
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
            label.append(checkbox, document.createTextNode(labelText));
            choices.append(label);
        });
        const wrap = table.closest('.table-wrap, .stock-table-wrap, .cash-table-wrap, .items-table-wrap');
        (wrap || table).before(badge, control);
        if (hidden.length) apply();
        refresh(table, state);
        state.control = control;
        state.update = () => {
            if (hidden.length) apply();
            refresh(table, state);
        };
    }

    function setupTables() {
        content?.querySelectorAll('table').forEach(setupTable);
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
    if (content) new MutationObserver(records => {
        const changed = new Set();
        let discover = false;
        for (const record of records) {
            const table = record.target.closest?.('table');
            if (table) {
                changed.add(table);
                continue;
            }
            for (const node of record.removedNodes) {
                if (node.nodeType !== 1) continue;
                const removed = node.matches('table') ? [node] : node.querySelectorAll('table');
                for (const old of removed) {
                    const state = tables.get(old);
                    if (state && !content.contains(old) && content.contains(state.control)) {
                        state.control.remove();
                        state.badge.remove();
                        tables.delete(old);
                    }
                }
            }
            if (!discover) discover = Array.from(record.addedNodes).some(node =>
                node.nodeType === 1 && (node.matches('table') || node.querySelector('table')));
        }
        if (discover || [...changed].some(table => !tables.has(table))) setupTables();
        changed.forEach(table => tables.get(table)?.update());
    }).observe(content, {childList: true, subtree: true});
})();
