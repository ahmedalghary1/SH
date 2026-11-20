const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { test } = require('node:test');
const source = fs.readFileSync('static/service-worker.js', 'utf8');
const staticCache = `${source.match(/const CACHE_VERSION = "([^"]+)"/)[1]}-static`;

function worker() {
    const handlers = {}, stores = new Map();
    const workerNavigator = {onLine: true};
    let fetcher = async () => new Response('network');
    let blocked = false;
    const caches = {
        async keys() { return [...stores.keys()]; },
        async delete(key) { return stores.delete(key); },
        async open(name) {
            if (blocked) throw new Error('Cache storage denied');
            if (!stores.has(name)) stores.set(name, new Map());
            const entries = stores.get(name);
            const key = (request) => typeof request === 'string' ? request : request.url;
            return {
                async put(request, response) { entries.set(key(request), response.clone()); },
                async match(request, options = {}) {
                    const response = entries.get(key(request));
                    if (!options.ignoreVary && response?.headers.get('Vary') === 'Accept' && request.headers?.get('Accept')) return;
                    return response?.clone();
                },
                async keys() { return [...entries.keys()].map(url => new Request(url)); },
                async delete(request) { return entries.delete(key(request)); },
            };
        },
    };
    vm.runInNewContext(source, {
        URL, Request, Response, Headers, Map, Set, Promise, AbortController, setTimeout, clearTimeout, caches,
        fetch: (...args) => fetcher(...args),
        self: { navigator: workerNavigator, location: { origin: 'https://erp.test' }, clients: { claim: async () => {}, matchAll: async () => [] }, addEventListener(type, callback) { handlers[type] = callback; }, skipWaiting: async () => {} },
    });
    return {
        stores, handlers, fetch(fn) { fetcher = fn; }, denyStorage() { blocked = true; },
        setOnline(online) { workerNavigator.onLine = online; },
        async navigate(path, method = 'GET', workspace = false, clientId = 'page-1') {
            let result, background;
            handlers.fetch({ request: { url: 'https://erp.test' + path, method,
                mode: workspace ? 'cors' : 'navigate', destination: workspace ? '' : 'document',
                headers: new Headers(workspace ? { 'X-Workspace-Tab': '1' } : {}),
            }, clientId, resultingClientId: clientId, waitUntil(promise) { background = promise; },
                respondWith(promise) { result = promise; } });
            await background;
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

test('offline stylesheets match precached public files despite Accept and version query differences', async () => {
    const w = worker();
    const css = 'https://erp.test/static/css/main.css';
    w.stores.set(staticCache, new Map([
        [css, new Response('body {display:block}', {headers: {'Content-Type': 'text/css', 'Vary': 'Accept'}})],
    ]));
    w.setOnline(false);
    w.fetch(async () => { throw new Error('offline'); });
    for (const url of [css, css + '?v=1']) {
        let response;
        w.handlers.fetch({
            request: new Request(url, {headers: {'Accept': 'text/css,*/*;q=0.1'}}),
            respondWith(value) { response = value; },
        });
        assert.equal(await (await response).text(), 'body {display:block}');
    }
});

test('prepared create screens survive browsing more than the private cache limit', async () => {
    const w = worker();
    const scope = 'u1-b1-rmanager-s0';
    const path = '/customers/simple/create/';
    w.fetch(async request => {
        const url = new URL(request.url);
        const type = url.pathname.endsWith('.js') ? 'text/javascript'
            : url.pathname.endsWith('.css') ? 'text/css'
            : url.pathname.endsWith('.json') ? 'application/json' : 'text/html';
        return url.pathname.startsWith('/static/') || url.pathname === '/manifest.json' || url.pathname === '/offline/'
            ? new Response('asset', {headers: {'Content-Type': type}})
            : privateResponse(scope, url.pathname);
    });
    let prepared;
    w.handlers.message({
        data: {type: 'CACHE_URLS', urls: [path], requiredUrls: [path], scope},
        waitUntil(value) { prepared = value; },
    });
    await prepared;
    for (let i = 1; i <= 101; i++) await w.navigate(`/products/${i}/`);
    w.setOnline(false);
    assert.equal(await (await w.navigate(path)).text(), path);
    assert.equal((await w.navigate('/products/1/')).headers.get('X-PWA-Local'), null);
});

test('an incomplete release cannot install or remove the previous offline shell', async () => {
    const w = worker();
    const oldCache = 'sh-pwa-vprevious-static';
    w.stores.set(oldCache, new Map());
    const asset = request => {
        const {pathname} = new URL(request.url);
        return new Response('asset', {headers: {'Content-Type': pathname.endsWith('.js') ? 'text/javascript' : pathname.endsWith('.css') ? 'text/css' : 'application/json'}});
    };
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
    w.fetch(async () => new Response('login', {headers: {'Content-Type': 'text/html'}}));
    await w.navigate('/accounts/login/');
    assert.equal([...w.stores.keys()].filter(key => key.includes('-pages-')).length, 0);
    w.fetch(async () => { throw new Error('offline'); });
    assert.equal((await w.navigate('/orders/')).status, 503);
});

test('late authenticated responses cannot replace a newer account or restore a signed-out session', async () => {
    const w = worker();
    let finish;
    w.fetch(() => new Promise(resolve => { finish = resolve; }));
    const oldPage = w.navigate('/', 'GET', false, 'old-tab');
    w.fetch(async () => privateResponse('u2-b1-rmanager-s0', 'new account'));
    await w.navigate('/');
    finish(privateResponse('u1-b1-rmanager-s0', 'previous account'));
    await oldPage;
    w.setOnline(false);
    assert.equal(await (await w.navigate('/')).text(), 'new account');
    assert.equal((await w.navigate('/', 'GET', false, 'old-tab')).status, 503);

    w.setOnline(true);
    w.fetch(() => new Promise(resolve => { finish = resolve; }));
    const beforeLogout = w.navigate('/');
    await w.navigate('/accounts/logout/', 'POST');
    finish(privateResponse('u2-b1-rmanager-s0'));
    await beforeLogout;
    w.setOnline(false);
    assert.equal((await w.navigate('/')).status, 503);
});

test('account management and unavailable sign-in never discard a prepared offline installation', async () => {
    const w = worker();
    const scope = 'u1-b1-rmanager-s0';
    w.fetch(async request => privateResponse(scope, new URL(request.url).pathname));
    await w.navigate('/');
    await w.navigate('/invoices/');
    await w.navigate('/accounts/users/');
    w.fetch(async () => { throw new Error('offline'); });
    for (const path of ['/accounts/branches/', '/admin/', '/accounts/login/']) {
        assert.equal((await w.navigate(path)).status, 503);
        assert.equal(await (await w.navigate('/')).text(), '/');
        assert.equal(await (await w.navigate('/invoices/', 'GET', true)).text(), '/invoices/');
    }
});

test('a dispatched POST is never intercepted or automatically replayed', async () => {
    const w = worker();
    let dispatched = 0;
    w.fetch(async () => { dispatched++; throw new Error('response lost'); });
    assert.equal(await w.navigate('/orders/create/', 'POST'), undefined);
    assert.equal(dispatched, 0);
});

test('preparation repairs a missing launch identity only after a verified online response', async () => {
    const w = worker();
    const scope = 'u1-b1-rmanager-s0';
    const launch = privateResponse(scope, 'home');
    launch.headers.set('Date', new Date().toUTCString());
    w.fetch(async () => launch.clone());
    await w.navigate('/');
    w.stores.get('sh-pwa-identity-v1').delete('/__pwa_identity__');

    async function prepare(online) {
        let done, result;
        w.fetch(async request => {
            const path = new URL(request.url).pathname;
            if (path === '/') {
                if (!online) throw new Error('offline');
                assert.equal(request.headers.get('X-PWA-Scope'), scope);
                return launch.clone();
            }
            return new Response('asset', {headers: {'Content-Type': path.endsWith('.js') ? 'text/javascript'
                : path.endsWith('.css') ? 'text/css' : 'application/json'}});
        });
        w.handlers.message({data: {type: 'CACHE_URLS', scope, urls: ['/']},
            ports: [{postMessage(value) { result = value; }}], waitUntil(value) { done = value; }});
        await done;
        return result;
    }
    assert.ok((await prepare(false)).failed.includes('/'));
    assert.ok((await prepare(true)).cached.includes('/'));
    const saved = w.stores.get('sh-pwa-identity-v1').get('/__pwa_identity__');
    assert.equal((await saved.json()).scope, scope);
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

test('denied or failed Cache Storage produces visible fallback HTML instead of a rejected navigation', async () => {
    const w = worker();
    w.denyStorage();
    w.fetch(async () => {throw new Error('offline');});
    const response = await w.navigate('/');
    assert.equal(response.status, 503);
    assert.match(response.headers.get('content-type'), /text\/html/);
    assert.match(await response.text(), /الاتصال غير متاح/);
});

test('an empty gateway failure before first preparation produces visible offline HTML', async () => {
    const w = worker();
    w.fetch(async () => new Response('', {status:503}));
    const response = await w.navigate('/');
    assert.match(await response.text(), /الاتصال غير متاح/);
});

test('installed start URL query parameters reuse the verified root document', async () => {
    const w = worker();
    w.fetch(async () => privateResponse('u1-b1-rmanager-s0', 'start page'));
    await w.navigate('/');
    w.fetch(async () => {throw new Error('offline');});
    const response = await w.navigate('/?source=installed');
    assert.equal(await response.text(), 'start page');
    assert.equal(response.headers.get('X-PWA-Local'), '1');
});

test('legacy cached superuser HTML receives its verified server scope when opened offline', async () => {
    const w = worker();
    w.fetch(async () => privateResponse('u7-ball-rmanager-s1', '<body data-pwa-branch-id="3"><section data-page-content>SH</section></body>'));
    await w.navigate('/');
    w.setOnline(false);
    const html = await (await w.navigate('/')).text();
    assert.match(html, /<body data-pwa-scope="u7-ball-rmanager-s1"/);
    assert.match(html, /data-pwa-local="1"/);
});

test('a disconnected installed app opens its cached launch UI without waiting for a network request', async () => {
    const w = worker();
    w.fetch(async () => privateResponse('u1-b1-rmanager-s0', 'instant local shell'));
    await w.navigate('/');
    w.setOnline(false);
    let requested = false;
    w.fetch(() => {requested = true; return new Promise(() => {});});
    assert.equal(await (await w.navigate('/')).text(), 'instant local shell');
    assert.equal(requested, false);
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
    assert.equal(await w.navigate('/accounts/logout/', 'POST'), undefined);
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
