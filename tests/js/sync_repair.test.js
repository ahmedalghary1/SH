const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { test } = require('node:test');

const source = fs.readFileSync('static/js/pwa/sync-engine.js', 'utf8');

test('only legacy customer collection conflicts are retried with a fresh key', async () => {
    const declaration = source.match(/async function repairLegacyCollectionConflicts\([^]*?\n\}/);
    assert.ok(declaration);
    const rows = [
        { id: 'date', entity_name: 'cash', status: 'conflict', error: 'التاريخ المدخل غير صالح.', idempotency_key: 'old-date', payload: { original_url: '/finance/transactions/collection/' } },
        { id: 'account', entity_name: 'cash', status: 'conflict', error: 'الخزنة غير متاحة لهذا الحساب.', idempotency_key: 'old-account', payload: { original_url: '/finance/transactions/collection/' } },
        { id: 'other', entity_name: 'cash', status: 'conflict', error: 'الرصيد غير كاف', idempotency_key: 'old-other', payload: { original_url: '/finance/transactions/collection/' } },
    ];
    const updated = [];
    let counter = 0;
    const context = vm.createContext({
        Set,
        STORE_NAMES: { syncQueue: 'queue' },
        getAll: async () => rows,
        putRecord: async (_store, row) => updated.push(row),
        uuid: () => `new-${++counter}`,
        nowIso: () => '2026-10-19T00:00:00Z',
    });
    vm.runInContext(declaration[0], context);
    await context.repairLegacyCollectionConflicts();
    assert.deepEqual(updated.map(row => row.id), ['date', 'account']);
    assert.deepEqual(updated.map(row => row.idempotency_key), ['new-1', 'new-2']);
    assert.ok(updated.every(row => row.status === 'pending'));
});
