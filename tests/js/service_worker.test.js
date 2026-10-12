const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { test } = require('node:test');
const source = fs.readFileSync('static/service-worker.js', 'utf8');

function worker() {
    const handlers = {}, stores = new Map();
    let fetcher = async () => new Response('network');
    const caches = {
        async keys() { return [...stores.keys()]; },
        async delete(key) { return stores.delete(key); },
        async open(name) {
            if (!stores.has(name)) stores.set(name, new Map());
            const entries = stores.get(name);
            const key = (request) => typeof request === 'string' ? request : request.url;
            return {
                async put(request, response) { entries.set(key(request), response.clone()); },
                async match(request) { return entries.get(key(request))?.clone(); },
                async keys() { return [...entries.keys()].map(url => new Request(url)); },
                async delete(request) { return entries.delete(key(request)); },
            };
        },
    };
    vm.runInNewContext(source, {
        URL, Request, Response, Map, Set, Promise, AbortController, setTimeout, clearTimeout, caches,
        fetch: (...args) => fetcher(...args),
        self: { location: { origin: 'https://erp.test' }, clients: { claim: async () => {}, matchAll: async () => [] }, addEventListener(type, callback) { handlers[type] = callback; }, skipWaiting: async () => {} },
    });
    return {
        stores, handlers, fetch(fn) { fetcher = fn; },
        async navigate(path, method = 'GET') {
            let result;
            handlers.fetch({ request: { url: 'https://erp.test' + path, method, mode: 'navigate', destination: 'document' }, clientId: 'page-1', resultingClientId: 'page-1', respondWith(promise) { result = promise; } });
            return result;
        },
    };
}
const privateResponse = (scope, text = 'private') => new Response(text, { headers: { 'Content-Type': 'text/html', 'X-PWA-Scope': scope, 'X-PWA-Cacheable': '1', 'Vary': 'Cookie' } });

test('only verified private HTML is cached and another account cannot read it offline', async () => {
    const w = worker();
    w.fetch(async () => privateResponse('u1-b1-rmanager-s0', 'account A'));
    assert.equal(await (await w.navigate('/orders/')).text(), 'account A');
    w.fetch(async () => { throw new Error('offline'); });
    assert.equal(await (await w.navigate('/orders/')).text(), 'account A');
    w.fetch(async () => privateResponse('u2-b1-rmanager-s0', 'account B'));
    await w.navigate('/products/');
    w.fetch(async () => { throw new Error('offline'); });
    assert.equal((await w.navigate('/orders/')).status, 503);
});

test('authentication navigation clears private cached pages', async () => {
    const w = worker();
    w.fetch(async () => privateResponse('u1-b1-rmanager-s0'));
    await w.navigate('/orders/');
    w.fetch(async () => new Response('login'));
    await w.navigate('/accounts/login/');
    assert.equal([...w.stores.keys()].filter(key => key.includes('-pages-')).length, 0);
    w.fetch(async () => { throw new Error('offline'); });
    assert.equal((await w.navigate('/orders/')).status, 503);
});

test('a dispatched POST is never intercepted or automatically replayed', async () => {
    const w = worker();
    let dispatched = 0;
    w.fetch(async () => { dispatched++; throw new Error('response lost'); });
    assert.equal(await w.navigate('/orders/create/', 'POST'), undefined);
    assert.equal(dispatched, 0);
});

test('permission errors and server 500 are visible instead of stale offline data', async () => {
    const w = worker();
    w.fetch(async () => privateResponse('u1-b1-rmanager-s0'));
    await w.navigate('/orders/');
    for (const status of [403, 500]) {
        w.fetch(async () => new Response('error', { status }));
        assert.equal((await w.navigate('/orders/')).status, status);
    }
});

test('HTML without scope or with no-store is never cached', async () => {
    const w = worker();
    w.fetch(async () => new Response('secret', { headers: { 'Content-Type': 'text/html' } }));
    await w.navigate('/orders/');
    w.fetch(async () => new Response('secret', { headers: { 'Content-Type': 'text/html', 'X-PWA-Scope': 'u1-b1-rmanager-s0', 'X-PWA-Cacheable': '1', 'Cache-Control': 'no-store' } }));
    await w.navigate('/orders/');
    w.fetch(async () => { throw new Error('offline'); });
    assert.equal((await w.navigate('/orders/')).status, 503);
});
