const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { test } = require('node:test');
const context = vm.createContext({});
const db = fs.readFileSync('static/js/pwa/db.js', 'utf8');
vm.runInContext(db.match(/export function calculateOrderTotals\([^]*?\n\}/)[0].replace('export ', ''), context);
vm.runInContext(fs.readFileSync('static/js/pwa/customer-ledger.js', 'utf8')
    .replace(/^import .*;\s*/m, '').replace('export function ', 'function '), context);
const customer = { server_id: 5, statement_snapshot: { downloaded_at: '2026-11-16T08:00:00Z', entries: [
    { date: '2026-11-15', type: 'opening', debit: '100', credit: '0', balance: '100' },
] } };
const sale = (extra = {}) => ({ created_at: '2026-11-16T10:00:00Z',
    order: { customer_server_id: 5, document_type: 'sale', action: 'confirm', paid_amount: '10' },
    items: [{ quantity: 2, unit_price: '30' }], ...extra });
const payment = (extra = {}) => ({ created_at: '2026-11-16T11:00:00Z',
    original_url: '/finance/transactions/collection/', payment: { customer: 5, amount: '20' }, ...extra });

test('offline statement adds a confirmed sale and receipt exactly once to downloaded balance', () => {
    const result = context.localCustomerStatement(customer, [sale()], [payment()]);
    assert.equal(result.balance, '130.00');
    assert.equal(result.entries.filter(entry => entry.local).length, 2);
    assert.equal(customer.statement_snapshot.entries.length, 1);
});
test('quotes, drafts and other customers cannot change this customer balance', () => {
    const rows = [sale({ order: { customer_server_id: 5, document_type: 'quote', action: 'confirm' } }),
        sale({ order: { customer_server_id: 5, action: 'hold' } }),
        sale({ order: { customer_server_id: 7, action: 'confirm' } })];
    assert.equal(context.localCustomerStatement(customer, rows, [payment({ payment: { customer: 7, amount: '20' } })]).balance, '100.00');
});
test('acknowledged local records already in the downloaded ledger are not counted twice', () => {
    const downloaded = { ...customer, statement_snapshot: { entries: [
        { balance: '130', order_id: 22, payment_id: 33 },
    ] } };
    assert.equal(context.localCustomerStatement(downloaded, [sale({ server_id: 22 })], [payment({ server_id: 33 })]).balance, '130.00');
});
test('decimal amounts retain cents and an absent snapshot is explicit', () => {
    const result = context.localCustomerStatement(customer, [], [payment({ payment: { customer: 5, amount: '0.10' } }), payment({ payment: { customer: 5, amount: '0.20' } })]);
    assert.equal(result.balance, '99.70');
    assert.throws(() => context.localCustomerStatement({ server_id: 5 }, [], []), /.+/);
});

test('a collection receipt allocated to other ledger entries is not counted a second time', () => {
    const downloaded = { ...customer, statement_snapshot: { payment_ids: [33], entries: [
        { balance: '80', payment_id: 34 },
    ] } };
    assert.equal(context.localCustomerStatement(downloaded, [], [payment({ server_id: 33 })]).balance, '80.00');
});
