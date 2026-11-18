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
        URL, Request, Response, Headers, Map, Set, Promise, AbortController, setTimeout, clearTimeout, caches,
        fetch: (...args) => fetcher(...args),
        self: { location: { origin: 'https://erp.test' }, clients: { claim: async () => {}, matchAll: async () => [] }, addEventListener(type, callback) { handlers[type] = callback; }, skipWaiting: async () => {} },
    });
    return {
        stores, handlers, fetch(fn) { fetcher = fn; },
        async navigate(path, method = 'GET', workspace = false) {
            let result;
            handlers.fetch({ request: { url: 'https://erp.test' + path, method,
                mode: workspace ? 'cors' : 'navigate', destination: workspace ? '' : 'document',
                headers: new Headers(workspace ? { 'X-Workspace-Tab': '1' } : {}),
            }, clientId: 'page-1', resultingClientId: 'page-1', respondWith(promise) { result = promise; } });
            return result;
        },
    };
}
const privateResponse = (scope, text = 'private') => new Response(text, { headers: { 'Content-Type': 'text/html', 'X-PWA-Scope': scope, 'X-PWA-Cacheable': '1', 'Vary': 'Cookie' } });

test('an incomplete update cannot replace the installed worker or its offline assets', async () => {
    const w = worker();
    const previous = new Map([['https://erp.test/static/js/main.js', new Response('working old code')]]);
    w.stores.set('sh-pwa-vprevious-static', previous);
    const missing = new Set(['/static/js/main.js']);
    w.fetch(async request => {
        const path = new URL(request.url).pathname;
        if (missing.has(path)) return new Response('missing', {status: 404});
        const type = path.endsWith('.js') ? 'text/javascript' : path.endsWith('.css') ? 'text/css' : path.endsWith('.json') ? 'application/manifest+json' : 'text/html';
        return new Response('asset', {headers: {'Content-Type': type}});
    });
    let installation;
    w.handlers.install({waitUntil(value) { installation = value; }});
    await assert.rejects(installation, /main\.js/);
    assert.equal(w.stores.get('sh-pwa-vprevious-static'), previous);
    missing.clear();
    w.handlers.install({waitUntil(value) { installation = value; }});
    await installation;
});

test('a proxy HTML response cannot masquerade as a JavaScript offline asset', async () => {
    const w = worker();
    w.fetch(async () => new Response('<html>proxy error</html>', {headers: {'Content-Type': 'text/html'}}));
    let installation;
    w.handlers.install({waitUntil(value) { installation = value; }});
    await assert.rejects(installation, /main\.js/);
});

test('an incomplete release cannot install or remove the previous offline shell', async () => {
    const w = worker();
    const oldCache = 'sh-pwa-vprevious-static';
    w.stores.set(oldCache, new Map());
    const asset = request => new Response('asset', {headers: {'Content-Type': request.url.endsWith('.js') ? 'text/javascript' : request.url.endsWith('.css') ? 'text/css' : 'application/json'}});
    w.fetch(async request => request.url.endsWith('/pwa/install.js') ? new Response('missing', {status: 404}) : asset(request));
    let done;
    w.handlers.install({waitUntil(value) { done = value; }});
    await assert.rejects(done, /install\.js/);
    assert.ok(w.stores.has(oldCache));
    w.fetch(async request => asset(request));
    w.handlers.install({waitUntil(value) { done = value; }});
    await done;
});

test('backup requests bypass the worker and its page timeout entirely', async () => {
    const w = worker();
    let fetches = 0;
    w.fetch(async () => { fetches++; return privateResponse('u1-ball-rmanager-s1', 'sensitive backup'); });
    for (const path of ['/settings/backups/', '/settings/backups/download/', '/settings/backups/74ecf151-89fa-4ebe-a16e-10993aa3b0a5/']) {
        assert.equal(await w.navigate(path, 'GET', true), undefined);
    }
    assert.equal(fetches, 0);
    assert.equal([...w.stores.keys()].filter(key => key.includes('-pages-')).length, 0);
});

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

test('workspace navigation uses scoped cached HTML when offline', async () => {
    const w = worker();
    w.fetch(async () => privateResponse('u1-b1-rsales-s0', 'collection form'));
    await w.navigate('/finance/transactions/collection/', 'GET', true);
    w.fetch(async () => { throw new Error('offline'); });
    assert.equal(await (await w.navigate('/finance/transactions/collection/', 'GET', true)).text(), 'collection form');
});

test('an unseen customer statement URL uses its generic shell within the verified scope only', async () => {
    const w = worker();
    w.fetch(async () => privateResponse('u1-b1-rsales-s0', 'statement shell'));
    await w.navigate('/finance/statements/customer/');
    w.fetch(async () => { throw new Error('offline'); });
    assert.equal(await (await w.navigate('/finance/statements/customer/?customer=123')).text(), 'statement shell');
    w.fetch(async () => privateResponse('u2-b1-rsales-s0', 'other user'));
    await w.navigate('/orders/');
    w.fetch(async () => { throw new Error('offline'); });
    assert.equal((await w.navigate('/finance/statements/customer/?customer=123')).status, 503);
});

test('worker updates retain verified pages from older releases', async () => {
    const w = worker();
    const scope = 'u1-b1-rsales-s0';
    w.fetch(async () => privateResponse(scope));
    await w.navigate('/');
    w.stores.set(`sh-pwa-vold-pages-${scope}`, new Map([
        ['https://erp.test/orders/create/', privateResponse(scope, 'old prepared form')],
        ['https://erp.test/forbidden/', privateResponse('u9-b1-rsales-s0', 'wrong account')],
    ]));
    let done;
    w.handlers.activate({waitUntil(value) { done = value; }});
    await done;
    w.fetch(async () => { throw new Error('long offline'); });
    assert.equal(await (await w.navigate('/orders/create/')).text(), 'old prepared form');
    assert.equal((await w.navigate('/forbidden/')).status, 503);
});

test('an expired session keeps offline work available and explicit logout still clears it', async () => {
    const w = worker();
    w.fetch(async () => privateResponse('u1-b1-rsales-s0', 'prepared form'));
    await w.navigate('/orders/create/');
    w.fetch(async () => {
        const response = new Response('login page');
        Object.defineProperty(response, 'redirected', {value:true});
        Object.defineProperty(response, 'url', {value:'https://erp.test/accounts/login/'});
        return response;
    });
    const offline = await w.navigate('/orders/create/');
    assert.equal(await offline.text(), 'prepared form');
    assert.equal(offline.headers.get('X-PWA-Local'), '1');
    await w.navigate('/accounts/logout/');
    w.fetch(async () => { throw new Error('offline'); });
    assert.equal((await w.navigate('/orders/create/')).status, 503);
});

test('opaque browser navigation redirects fall back only when the session has expired', async () => {
    const w = worker();
    w.fetch(async () => privateResponse('u1-b1-rsales-s0', '<section data-page-content>prepared form</section>'));
    await w.navigate('/orders/create/');
    const redirect = new Response(null);
    Object.defineProperty(redirect, 'type', {value: 'opaqueredirect'});
    let expired = true;
    w.fetch(async request => {
        if (String(request).endsWith('/api/sync/session/')) {
            if (!expired) return new Response('{}', {headers: {'Content-Type': 'application/json'}});
            const login = new Response('login');
            Object.defineProperties(login, {redirected: {value: true}, url: {value: 'https://erp.test/accounts/login/?next=/api/sync/session/'}});
            return login;
        }
        return redirect;
    });
    const local = await w.navigate('/orders/create/');
    assert.equal(local.headers.get('X-PWA-Local'), '1');
    assert.match(await local.text(), /data-pwa-local="1"/);
    expired = false;
    assert.equal(await w.navigate('/orders/create/'), redirect);
});

test('unseen list filters reuse the local shell without substituting a quote form', async () => {
    const w = worker();
    w.fetch(async () => privateResponse('u1-b1-rsales-s0', 'list shell'));
    await w.navigate('/orders/');
    await w.navigate('/orders/create/');
    w.fetch(async () => { throw new Error('offline'); });
    assert.equal(await (await w.navigate('/orders/?q=new-search&page=99')).text(), 'list shell');
    assert.equal((await w.navigate('/orders/create/?document=quote')).status, 503);
});
