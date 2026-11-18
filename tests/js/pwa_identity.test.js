const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {test} = require('node:test');
const source = fs.readFileSync('static/js/pwa/identity.js', 'utf8').replace(/export /g, '');

function identity(data) {
    const context = vm.createContext({document: {body: {dataset: data}}});
    vm.runInContext(source, context);
    return context;
}

test('server all-branches scope takes precedence over an assigned superuser branch in old HTML', () => {
    const context = identity({pwaScope: 'u7-ball-rmanager-s1', pwaUserId: '7', pwaBranchId: '3', pwaRole: 'manager', pwaSuperuser: '1'});
    assert.equal(context.getOfflineScope(), 'u7-ball-rmanager-s1');
    assert.equal(context.databaseName(), 'sh-offline-db-u7-ball-rmanager-s1');
});

test('explicit scope must belong to the authenticated page user, role and privileges', () => {
    for (const scope of ['u8-ball-rmanager-s1', 'u7-ball-rsales-s1', 'u7-ball-rmanager-s0', 'invalid']) {
        const context = identity({pwaScope: scope, pwaUserId: '7', pwaBranchId: '', pwaRole: 'manager', pwaSuperuser: '1'});
        assert.equal(context.getOfflineScope(), null);
        assert.throws(() => context.databaseName());
    }
});

test('legacy branch pages retain their database identity without merging or deleting pending work', () => {
    const context = identity({pwaUserId: '7', pwaBranchId: '3', pwaRole: 'sales', pwaSuperuser: '0'});
    assert.equal(context.databaseName(), 'sh-offline-db-u7-b3-rsales-s0');
});
