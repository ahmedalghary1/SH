const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {test} = require('node:test');
const context = vm.createContext({});
const source = fs.readFileSync('static/js/pwa/db.js', 'utf8');
vm.runInContext(source.match(/function durableTransaction\([^]*?\n\}/)[0], context);

test('unsent records request strict durability and older browsers can still save', () => {
    const calls = [];
    const db = {transaction(...args) {calls.push(args); return 'transaction';}};
    assert.equal(context.durableTransaction(db, ['queue']), 'transaction');
    assert.equal(calls[0][2].durability, 'strict');
    db.transaction = (...args) => {calls.push(args); if (args.length === 3) throw new TypeError('Old browser'); return 'fallback';};
    assert.equal(context.durableTransaction(db, ['queue']), 'fallback');
    assert.equal(calls.at(-1).length, 2);
});

test('storage failures are never hidden by retrying a different transaction mode', () => {
    let calls = 0;
    const db = {transaction() {calls++; throw Object.assign(Error('full'), {name:'QuotaExceededError'});}};
    assert.throws(() => context.durableTransaction(db, ['queue']), /full/);
    assert.equal(calls, 1);
});
