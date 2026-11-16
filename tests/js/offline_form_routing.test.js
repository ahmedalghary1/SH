const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { test } = require('node:test');
const source = fs.readFileSync('static/js/pwa/offline-forms.js', 'utf8');

test('customer return reconciliation cannot be queued as a customer save', () => {
    assert.equal(routing().classifyPath('/customers/42/reconcile-returns/'), null);
});

function routing() {
    const context = vm.createContext({ URL, window: { location: { origin: 'https://erp.test', href: 'https://erp.test/orders/create/' } } });
    for (const name of ['pathFromAction', 'formPath', 'classifyPath', 'shouldCaptureForm']) {
        const declaration = source.match(new RegExp(`function ${name}\\([^]*?\\n\\}`));
        assert.ok(declaration, `Missing route helper ${name}`);
        vm.runInContext(declaration[0], context);
    }
    return context;
}

test('cashier submit buttons named action cannot hide the invoice offline route', () => {
    const context = routing();
    const form = { action: { toString: () => '[object RadioNodeList]' }, getAttribute: name => name === 'method' ? 'post' : null };
    assert.equal(context.formPath(form), '/orders/create/');
    assert.equal(context.shouldCaptureForm(form), true);
});

test('relative form actions and explicit submit overrides use the intended route', () => {
    const context = routing();
    const form = { getAttribute: name => name === 'action' ? '../1/update/' : 'post' };
    assert.equal(context.formPath(form), '/orders/1/update/');
    assert.equal(context.shouldCaptureForm(form), false);
    const submitter = { getAttribute: () => '/invoices/1/delete/' };
    assert.equal(context.formPath(form, submitter), '/invoices/1/delete/');
    assert.equal(context.classifyPath(context.formPath(form, submitter)), null);
});

test('a reachable collection is dispatched once after a read-only connectivity check', async () => {
    const declaration = source.match(/async function handleCapturedSubmit\([^]*?\n\}/);
    assert.ok(declaration);
    const scheduled = [];
    let serverSubmits = 0;
    let queued = 0;
    let probes = 0;
    const context = vm.createContext({
        navigator: { onLine: true },
        window: {
            setTimeout(callback) { scheduled.push(callback); },
            SHUi: { markSaved() {} },
        },
        pendingSubmissions: new WeakSet(),
        getAll: async () => [], STORE_NAMES: {syncQueue:'queue'},
        submitNormally() { serverSubmits += 1; },
        queueFormSubmission() { queued += 1; },
        serverIsReachable: async () => { probes += 1; return true; },
    });
    vm.runInContext(declaration[0], context);
    const form = { isConnected: true, reportValidity() { return true; } };
    await context.handleCapturedSubmit(form);
    await scheduled.shift()();
    assert.equal(serverSubmits, 1);
    assert.equal(queued, 0);
    assert.equal(probes, 1);
});

test('an unreachable server queues before dispatch even when navigator reports online', async () => {
    const scheduled = [];
    let submitted = 0, queued = 0;
    const context = vm.createContext({
        navigator: { onLine: true }, CustomEvent: class {},
        window: { setTimeout(fn) { scheduled.push(fn); }, dispatchEvent() {} },
        pendingSubmissions: new WeakSet(), serverIsReachable: async () => false,
        getAll: async () => [], STORE_NAMES: {syncQueue:'queue'},
        submitNormally() { submitted++; }, validateOfflineForm: () => true,
        queueFormSubmission: async () => { queued++; return true; },
        showOfflineNotice() {}, processQueue() {},
    });
    vm.runInContext(source.match(/async function handleCapturedSubmit\([^]*?\n\}/)[0], context);
    await context.handleCapturedSubmit({ isConnected: true, dataset: {}, reportValidity: () => true });
    await scheduled.shift()();
    assert.equal(queued, 1);
    assert.equal(submitted, 0);
});

test('connectivity check performs a GET and returns false on a failed probe', async () => {
    let request;
    const context = vm.createContext({ navigator: { onLine: true }, AbortController,
        window: { setTimeout, clearTimeout },
        fetch: async (url, options) => { request = { url, options }; throw new TypeError('offline'); },
    });
    vm.runInContext(source.match(/async function serverIsReachable\([^]*?\n\}/)[0], context);
    assert.equal(await context.serverIsReachable(), false);
    assert.equal(request.url, '/api/sync/session/');
    assert.equal(request.options.method, undefined); // GET; no business POST was sent.
});
