const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {test} = require('node:test');
const source = fs.readFileSync('static/js/pwa/sync-engine.js', 'utf8');

test('readiness explains scope and missing-page failures and clears stale errors after success', () => {
    const badge = {};
    const context = vm.createContext({document: {querySelectorAll: () => [badge]}});
    vm.runInContext('let offlineReady = false; let readinessDetails = {};\n'
        + source.match(/function showOfflineReadiness\([^]*?\n\}/)[0], context);
    context.showOfflineReadiness({ready:false, reason:'scope_changed', error:'scope_changed'});
    assert.match(badge.textContent, /نطاق المعرض/);
    assert.equal(badge.title, 'scope_changed');
    context.showOfflineReadiness({ready:false, reason:'pages_missing', failed:['/orders/','/products/']});
    assert.match(badge.textContent, /2/);
    assert.equal(badge.title, '/orders/\n/products/');
    context.showOfflineReadiness({ready:true, reason:'ready'});
    assert.equal(badge.textContent, 'جاهز للعمل دون اتصال');
    assert.equal(badge.title, '');
});

test('worker readiness times out and allows a later successful retry', async () => {
    let expire, cleared = 0;
    const context = vm.createContext({
        navigator: { serviceWorker: { ready: new Promise(() => {}) } },
        window: {setTimeout(fn) { expire = fn; return 1; }, clearTimeout() { cleared++; }},
    });
    vm.runInContext(source.match(/async function readyWorkerRegistration\([^]*?\n\}/)[0], context);
    const waiting = context.readyWorkerRegistration();
    expire();
    await assert.rejects(waiting, /Service Worker/);
    assert.equal(cleared, 1);
    context.navigator.serviceWorker.ready = Promise.resolve({active: true});
    assert.equal((await context.readyWorkerRegistration()).active, true);
    assert.equal(cleared, 2);
});

test('persistence denial is rate limited across pages and retried after installation', async () => {
    let attempts = 0;
    const metadata = new Map();
    const context = vm.createContext({
        navigator: {storage: {persisted: async () => false, persist: async () => ++attempts > 1}},
        getMetadata: async key => metadata.get(key),
        setMetadata: async (key, value) => metadata.set(key, value), syncStatusEvent() {},
    });
    vm.runInContext('let persistenceAttempted = false;\n' + source.match(/async function ensurePersistentStorage\([^]*?\n\}/)[0], context);
    await context.ensurePersistentStorage();
    await context.ensurePersistentStorage();
    assert.equal(attempts, 1);
    assert.equal(metadata.get('storage_persistent'), false);
    vm.runInContext('persistenceAttempted = false;', context);
    await context.ensurePersistentStorage();
    assert.equal(attempts, 1);
    vm.runInContext('persistenceAttempted = false;', context);
    await context.ensurePersistentStorage(true);
    assert.equal(metadata.get('storage_persistent'), true);
});
