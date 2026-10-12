const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

class Element {
    constructor(tag = 'div') {
        this.tagName = tag.toUpperCase();
        this.dataset = {};
        this.attributes = {};
        this.listeners = {};
        this.children = [];
        this.textContent = '';
        this.value = '';
        this.classList = { add() {}, remove() {}, toggle() {}, contains() { return false; } };
    }
    addEventListener(type, handler) { (this.listeners[type] ||= []).push(handler); }
    emit(type, event = { target: this }) { for (const handler of this.listeners[type] || []) handler(event); }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    getAttribute(name) { return this.attributes[name] ?? null; }
    hasAttribute(name) { return Object.hasOwn(this.attributes, name); }
    removeAttribute(name) { delete this.attributes[name]; }
    append(...children) { this.children.push(...children); }
    appendChild(child) { this.children.push(child); return child; }
    querySelector(selector) { return this.selectors?.[selector] || null; }
    querySelectorAll(selector) { return this.allSelectors?.[selector] || []; }
    dispatchEvent(event) { this.emit(event.type, { ...event, target: this }); }
    focus() {}
    set innerHTML(_value) { this.children = []; }
}

function mainFixture(fetch = async () => { throw new TypeError('Network unavailable'); }) {
    const document = new Element();
    document.body = new Element('body');
    document.cookie = '';
    document.createElement = tag => new Element(tag);
    const window = new Element();
    window.location = { pathname: '/', origin: 'https://example.test', href: 'https://example.test/' };
    window.setInterval = () => {};
    window.matchMedia = () => ({ matches: false, addEventListener() {} });
    const timers = [];
    const navigator = { onLine: true };
    const context = { document, window, navigator, fetch, URL, console,
        setTimeout: fn => { timers.push(fn); return timers.length; }, clearTimeout() {},
    };
    vm.createContext(context);
    vm.runInContext(fs.readFileSync(path.resolve(__dirname, '../../static/js/main.js'), 'utf8'), context);
    return { context, document, window, navigator, flush: () => { while (timers.length) timers.shift()(); } };
}

function guardedForm(fixture, action = '/save/') {
    const form = new Element('form');
    form.method = 'post'; form.action = action;
    form.setAttribute('method', 'post'); form.setAttribute('action', action);
    form.checkValidity = () => true;
    form.selectors = { '[name="_submission_token"]': new Element('input') };
    const button = new Element('button'); button.textContent = 'حفظ';
    form.allSelectors = {
        'button[type="submit"], button:not([type]), input[type="submit"]': [button],
        '[data-submit-disabled]': [button],
    };
    form.querySelectorAll = selector => selector === '[data-submit-disabled]' ? (button.dataset.submitDisabled ? [button] : []) : (form.allSelectors[selector] || []);
    const root = new Element(); root.allSelectors = { form: [form] };
    fixture.context.enhanceSharedPageUi(root);
    return { form, button };
}

test('canceling validation or confirmation keeps save usable; accepted submission blocks duplicates', () => {
    const fixture = mainFixture();
    const { form, button } = guardedForm(fixture);
    const first = { defaultPrevented: false };
    form.emit('submit', first);
    first.defaultPrevented = true; // A later custom validator or confirmation cancels it.
    fixture.flush();
    assert.equal(form.dataset.submitting, undefined);
    assert.equal(Boolean(button.disabled), false);
    assert.equal(button.textContent, 'حفظ');

    form.emit('submit', { defaultPrevented: false });
    let prevented = false;
    form.emit('submit', { defaultPrevented: false, preventDefault() { prevented = true; } });
    fixture.flush();
    assert.equal(prevented, true);
    assert.equal(button.disabled, true);
    fixture.document.allSelectors = { 'form[data-submitting="1"]': [form] };
    fixture.window.emit('pageshow');
    assert.equal(button.disabled, false);
    assert.equal(button.textContent, 'حفظ');
});

test('download/export forms remain usable after producing a file', () => {
    const fixture = mainFixture();
    const { form, button } = guardedForm(fixture, '/invoices/export/excel/');
    form.emit('submit', { defaultPrevented: false });
    fixture.flush();
    assert.equal(form.dataset.submitting, undefined);
    assert.equal(Boolean(button.disabled), false);
});

test('an ambiguous failed POST is never queued again; offline POST is queued before dispatch', async () => {
    let offlineCalls = 0;
    let networkCalls = 0;
    const fixture = mainFixture(async () => { networkCalls++; throw new TypeError('Network unavailable'); });
    fixture.window.SHOffline = { handleJsonRequest: async () => { offlineCalls++; return { success: true, data: {} }; } };
    await assert.rejects(fixture.window.SHHttp.json('/save/', { method: 'POST' }), /تحقق من السجلات/);
    assert.equal(offlineCalls, 0);
    assert.equal(networkCalls, 1);
    await fixture.window.SHHttp.json('/stock/');
    assert.equal(offlineCalls, 1);
    fixture.navigator.onLine = false;
    await fixture.window.SHHttp.json('/save/', { method: 'POST' });
    assert.equal(offlineCalls, 2);
    assert.equal(networkCalls, 2);
});

test('server validation/permission failures are shown and never replaced by offline data', async () => {
    let offlineCalls = 0;
    const fixture = mainFixture(async () => ({ ok: false, headers: { get: () => 'application/json' }, json: async () => ({ success: false, message: 'لا توجد صلاحية' }) }));
    fixture.window.SHOffline = { handleJsonRequest: async () => { offlineCalls++; return { success: true }; } };
    await assert.rejects(fixture.window.SHHttp.json('/stock/'), /لا توجد صلاحية/);
    assert.equal(offlineCalls, 0);
});

test('phone numbers and document IDs are preserved while money keeps exact digits', () => {
    const fixture = mainFixture();
    const phone = new Element('td'); phone.textContent = '01012345678';
    const identifier = new Element('td'); identifier.textContent = '123456789';
    const amount = new Element('td'); amount.textContent = '12345.67';
    const root = new Element();
    root.allSelectors = { 'td, .stat-card strong, .summary-value, [data-number]': [phone, identifier, amount] };
    fixture.context.enhanceSharedPageUi(root);
    assert.equal(phone.textContent, '01012345678');
    assert.equal(identifier.textContent, '123456789');
    assert.equal(amount.textContent, '12,345.67');
});

test('purchase totals include discount/payment, and removing an earlier row preserves the correct edit target', () => {
    const form = new Element('form');
    const fields = Object.fromEntries(['id_product_variant', 'id_quantity', 'id_unit_cost', 'id_items_json', 'id_discount_type', 'id_discount_value', 'id_paid_amount'].map(id => [id, new Element('input')]));
    fields.id_items_json.value = JSON.stringify([1, 2, 3].map(id => ({ product_variant_id: String(id), product_name: `صنف ${id}`, quantity: id, unit_cost: 10 })));
    fields.id_product_variant.options = [{ textContent: 'صنف' }]; fields.id_product_variant.selectedIndex = 0;
    fields.id_discount_type.value = 'percent'; fields.id_discount_value.value = '10'; fields.id_paid_amount.value = '20';
    form.selectors = Object.fromEntries(['[data-purchase-items-body]', '[data-purchase-total]', '[data-add-purchase-item]', '[data-subtotal]', '[data-discount]', '[data-net]', '[data-purchase-summary-total]', '[data-purchase-summary-paid]', '[data-purchase-summary-remaining]'].map(selector => [selector, new Element()]));
    const document = { querySelector: () => form, getElementById: id => fields[id], createElement: tag => new Element(tag) };
    vm.runInNewContext(fs.readFileSync(path.resolve(__dirname, '../../static/js/purchase_create.js'), 'utf8'), { document, Event: class { constructor(type) { this.type = type; } }, window: { alert: message => { throw new Error(message); } } });
    assert.equal(form.selectors['[data-purchase-summary-total]'].textContent, '54.00');
    assert.equal(form.selectors['[data-purchase-summary-paid]'].textContent, '20.00');
    assert.equal(form.selectors['[data-purchase-summary-remaining]'].textContent, '34.00');
    const click = (selector, dataset) => form.emit('click', { preventDefault() {}, target: { closest: requested => requested === selector ? { dataset } : null } });
    click('[data-edit-purchase-item]', { editPurchaseItem: '2' });
    click('[data-remove-purchase-item]', { removePurchaseItem: '0' });
    fields.id_quantity.value = '9';
    click('[data-add-purchase-item]', {});
    const items = JSON.parse(fields.id_items_json.value);
    assert.equal(items.length, 2);
    assert.equal(items[0].product_variant_id, '2');
    assert.equal(items[0].quantity, 2);
    assert.equal(items[1].product_variant_id, '3');
    assert.equal(items[1].quantity, 9);
});
