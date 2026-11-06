const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

test('customer return search preserves selections and includes hidden rows in total', () => {
    const source = fs.readFileSync(path.join(__dirname, '../../templates/returns/customer_create.html'), 'utf8');
    const script = source.match(/<script>([\s\S]*?)<\/script>/)[1];
    const listeners = {};
    function row(search, price, quantity) {
        const selected = { checked: true };
        const input = { value: quantity };
        const refund = {};
        return {
            dataset: { search, price }, selected, input, refund, hidden: false,
            querySelector(selector) {
                if (selector === '[data-quantity]') return input;
                if (selector === '[data-refund]') return refund;
                return selected;
            },
        };
    }
    const rows = [row('قميص RET-001', '250.00', '2'), row('بنطلون RET-002', '150.00', '1')];
    const total = {};
    const noMatch = { hidden: true };
    const form = {
        dataset: {},
        querySelectorAll: () => rows,
        querySelector: selector => selector === '[data-total-refund]' ? total : noMatch,
        addEventListener: (name, fn) => { listeners[name] = fn; },
    };
    const search = { addEventListener: (_, fn) => { listeners.search = fn; } };
    vm.runInNewContext(script, {
        document: {
            querySelector: selector => selector === '[data-customer-return-form]' ? form : null,
            getElementById: () => search,
        },
        window: {},
    });
    assert.equal(total.textContent, '650.00');
    listeners.search({ target: { value: 'ret-001' } });
    assert.equal(rows[0].hidden, false);
    assert.equal(rows[1].hidden, true);
    assert.equal(rows[1].selected.checked, true);
    listeners.input();
    assert.equal(total.textContent, '650.00');
    listeners.search({ target: { value: 'بنطلون' } });
    assert.equal(rows[0].hidden, true);
    assert.equal(rows[1].hidden, false);
    listeners.search({ target: { value: 'missing' } });
    assert.equal(noMatch.hidden, false);
    listeners.search({ target: { value: '' } });
    assert.equal(noMatch.hidden, true);
    assert.ok(rows.every(item => !item.hidden));
    rows[0].selected.checked = false;
    listeners.change();
    assert.equal(total.textContent, '150.00');
});
