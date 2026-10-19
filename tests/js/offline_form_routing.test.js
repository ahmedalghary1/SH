const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { test } = require('node:test');
const source = fs.readFileSync('static/js/pwa/offline-forms.js', 'utf8');

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

test('an online collection submits to the server without a connectivity probe or local queue', async () => {
    const declaration = source.match(/async function handleCapturedSubmit\([^]*?\n\}/);
    assert.ok(declaration);
    const scheduled = [];
    let serverSubmits = 0;
    let queued = 0;
    const context = vm.createContext({
        navigator: { onLine: true },
        window: {
            setTimeout(callback) { scheduled.push(callback); },
            SHUnsavedForms: { markSaved() {} },
        },
        pendingSubmissions: new WeakSet(),
        submitNormally() { serverSubmits += 1; },
        queueFormSubmission() { queued += 1; },
    });
    vm.runInContext(declaration[0], context);
    const form = { isConnected: true, reportValidity() { return true; } };
    await context.handleCapturedSubmit(form);
    await scheduled.shift()();
    assert.equal(serverSubmits, 1);
    assert.equal(queued, 0);
});
