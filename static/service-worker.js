// Release all shell assets together; private pages require a verified scope.
const CACHE_VERSION = "sh-pwa-v2026-11-20-offline-navigation-01";
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const PAGE_PREFIX = 'sh-pwa-pages-v2-';
const META_CACHE = "sh-pwa-identity-v1";
const META_URL = "/__pwa_identity__";
const OFFLINE_URL = "/offline/";
const MAX_PAGES = 100;
const PINNED_PATHS = new Set(['/', '/orders/', '/orders/quotes/', '/orders/create/', '/invoices/',
  '/products/', '/products/create/', '/products/representative/create/', '/inventory/stock/',
  '/customers/', '/customers/list/', '/finance/statements/customer/', '/finance/transactions/collection/']);
const FILTERABLE_PATHS = new Set(['/orders/', '/orders/quotes/', '/invoices/', '/products/', '/customers/',
  '/customers/list/', '/inventory/stock/']);
const PREFETCH_FRESH_MS = 5 * 60 * 1000;
const CORE_ASSETS = [
  OFFLINE_URL, "/manifest.json", "/static/css/main.css", "/static/js/main.js",
  "/static/css/ui-spacing.css",
  "/static/css/table-controls.css", "/static/js/table-controls.js", "/static/js/table-navigation.js",
  "/static/css/customer-statement.css", "/static/js/customer-statement.js",
  "/static/js/pwa/customer-ledger.js",
  "/static/js/internal-tabs.js", "/static/js/orders.js", "/static/js/inventory.js",
  "/static/js/product_create.js", "/static/js/purchase_create.js", "/static/js/purchase_return.js",
  "/static/js/product_create.js?v=20260808-01",
  "/static/js/pwa/identity.js", "/static/js/pwa/db.js", "/static/js/pwa/sync-queue.js",
  "/static/js/pwa/install.js",
  "/static/js/pwa/sync-engine.js", "/static/js/pwa/offline-forms.js", "/static/js/pwa/offline-list-view.js",
  "/static/js/pwa/queue-view.js", "/static/js/bulk-transfer.js",
  "/static/js/pwa/local-pages.js",
  "/static/images/sh-family-Logo.png", "/static/fonts/cairo/Cairo-400.ttf",
  "/static/fonts/cairo/Cairo-600.ttf", "/static/fonts/cairo/Cairo-700.ttf",
  "/static/icons/icon-192.png", "/static/icons/icon-512.png",
];
const CORE_STATIC_PATHS = new Set(CORE_ASSETS.filter(path => path.startsWith('/static/') && !path.includes('?')));
const clientScopes = new Map();
let activeScope;
let scopeRevision = 0;
let navigationSequence = 0;
let lastIdentityNavigation = 0;
const validScope = (value) => /^u\d+-b(?:\d+|all)-r[a-z_]+-s[01]$/.test(value || "");
const sameOriginUrl = (input) => {
  try {
    const url = new URL(typeof input === "string" ? input : input.url, self.location.origin);
    return url.origin === self.location.origin ? url : null;
  } catch { return null; }
};
const isAuthUrl = (url) => url.pathname.startsWith("/accounts/") || url.pathname.startsWith("/admin/");
const isGatewayFailure = (response) => [502, 503, 504].includes(response.status);
const isPublicAsset = (url) => url.pathname.startsWith("/static/") || [OFFLINE_URL, "/manifest.json"].includes(url.pathname);
const isPrivatePage = (url) => !isAuthUrl(url) && !url.pathname.startsWith("/api/")
  && !url.pathname.startsWith("/settings/backups/")
  && !url.pathname.startsWith("/media/") && !/\.(?:pdf|csv|xlsx?|zip)$/i.test(url.pathname)
  && !["export", "download", "format"].some((key) => url.searchParams.has(key));

async function storedScope() {
  const cache = await caches.open(META_CACHE);
  const response = await cache.match(META_URL);
  const data = await response?.json().catch(() => null);
  return validScope(data?.scope) ? data.scope : null;
}

async function readActiveScope() {
  if (activeScope === undefined) {
    const saved = await storedScope();
    if (activeScope === undefined) activeScope = saved;
  }
  return activeScope;
}

async function setActiveScope(scope) {
  if (!scope || activeScope !== scope) scopeRevision++;
  activeScope = validScope(scope) ? scope : null;
  const cache = await caches.open(META_CACHE);
  await cache.put(META_URL, new Response(JSON.stringify({ scope: activeScope }), {
    headers: { "Content-Type": "application/json" },
  }));
}

async function clearScope(navigation = ++navigationSequence) {
  lastIdentityNavigation = navigation;
  await setActiveScope(null);
  clientScopes.clear();
  const keys = await caches.keys();
  await Promise.all(keys.filter((key) => key.startsWith(PAGE_PREFIX)).map((key) => caches.delete(key)));
  // Pending operations remain in account-specific IndexedDB for that account.
}

function canStore(response, url, scope) {
  if (!response || !response.ok || response.type === "opaque" || response.redirected) return false;
  if ((response.headers.get("cache-control") || "").toLowerCase().includes("no-store")) return false;
  if (isPublicAsset(url)) {
    const type = (response.headers.get('content-type') || '').toLowerCase();
    // Some proxies answer a missing script with a 200 HTML error/login page.
    // Such a response must not make an incomplete shell look ready.
    if (url.pathname.endsWith('.js')) return /(?:javascript|ecmascript)/.test(type);
    if (url.pathname.endsWith('.css')) return type.includes('text/css');
    if (url.pathname === '/manifest.json') return type.includes('json');
    return true;
  }
  return isPrivatePage(url) && validScope(scope)
    && response.headers.get("X-PWA-Scope") === scope
    && response.headers.get("X-PWA-Cacheable") === "1"
    && (response.headers.get("content-type") || "").includes("text/html");
}

async function storeResponse(request, response, scope) {
  const url = sameOriginUrl(request);
  if (!url || !canStore(response, url, scope)) return;
  const name = isPublicAsset(url) ? STATIC_CACHE : `${PAGE_PREFIX}${scope}`;
  // Retain Vary. Ignore it only when reading this account/branch's exact URL.
  try {
    const cache = await caches.open(name);
    await cache.put(new Request(url.href), response.clone());
    if (name.startsWith(PAGE_PREFIX)) {
      const metadata = await caches.open(META_CACHE);
      const saved = await metadata.match(`/__pwa_required_pages__/${scope}`);
      const required = new Set(await saved?.json() || []);
      const keys = (await cache.keys()).filter(key => {
        const {pathname, search} = new URL(key.url);
        return !required.has(pathname + search) && (search || !PINNED_PATHS.has(pathname));
      });
      await Promise.all(keys.slice(0, Math.max(0, keys.length - MAX_PAGES)).map((key) => cache.delete(key)));
    }
  } catch { /* A cache/quota error must never fail a successful network GET. */ }
}

async function offlineFallback(request) {
  if (request.headers?.get('X-Workspace-Tab') === '1') {
    return new Response(null, {status: 503, headers: {'X-PWA-Unavailable': '1'}});
  }
  try {
    const cache = await caches.open(STATIC_CACHE);
    const cached = await cache.match(OFFLINE_URL, {ignoreVary: true});
    if (cached) return cached;
  } catch { /* A disabled/full cache must still return a visible HTML screen. */ }
  return new Response(
    '<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>بدون اتصال — SH</title><body><main><h1>الاتصال غير متاح</h1><p>افتح الصفحة مرة أثناء الاتصال لتجهيزها للعمل بدون إنترنت. تسجيل الدخول والمزامنة يحتاجان إلى الاتصال.</p><button onclick="location.reload()">إعادة المحاولة</button></main></body></html>',
    { status: 503, headers: { "Content-Type": "text/html; charset=utf-8" } },
  );
}

async function cachedPage(request, clientId) {
  const scope = await readActiveScope();
  if (!scope || (clientScopes.has(clientId) && clientScopes.get(clientId) !== scope)) return null;
  const cache = await caches.open(`${PAGE_PREFIX}${scope}`);
  const exact = await cache.match(new Request(request.url), { ignoreVary: true });
  const local = async response => {
    if (!response || response.headers.get('X-PWA-Scope') !== scope) return null;
    const headers = new Headers(response.headers);
    headers.delete('Content-Length');
    headers.delete('Content-Encoding');
    headers.set('X-PWA-Local', '1');
    // The renderer must know a cache was used even when the OS reports online.
    const html = (await response.text())
      .replace(/<body\b([^>]*)>/i, (_tag, attributes) =>
        `<body data-pwa-scope="${scope}"${attributes.replace(/\sdata-pwa-scope=(?:"[^"]*"|'[^']*')/gi, '')}>`)
      .replace('data-page-content', 'data-pwa-local="1" data-page-content');
    return new Response(html, {status: 200, headers});
  };
  if (exact) return local(exact);
  // The customer is selected from the authorized local snapshot on this screen.
  const url = sameOriginUrl(request);
  if (url?.pathname === '/' || url?.pathname === '/finance/statements/customer/' || FILTERABLE_PATHS.has(url?.pathname)) {
    return local(await cache.match(new Request(new URL(url.pathname, self.location.origin)), { ignoreVary: true }));
  }
  const metadata = await caches.open(META_CACHE);
  const manifest = await metadata.match(`/__pwa_details__/${scope}`);
  const details = await manifest?.json().catch(() => []);
  if (details?.includes(url?.pathname)) {
    return local(await cache.match(new Request(new URL('/', self.location.origin)), {ignoreVary:true}));
  }
  return null;
}

async function networkNavigation(request, event) {
  const url = sameOriginUrl(request);
  if (!url) return fetch(request);
  const restricted = isAuthUrl(url);
  const localPage = () => restricted ? null : cachedPage(request, event.clientId);
  const navigation = ++navigationSequence;
  // A genuinely disconnected device should open its prepared UI immediately,
  // instead of showing a blank launch window until the network timeout expires.
  if (self.navigator?.onLine === false) {
    return (await localPage()) || offlineFallback(request);
  }
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 8000);
  try {
    const response = await fetch(request, { signal: controller.signal });
    // Account and admin screens are network-only. Merely visiting one (or
    // failing to reach login) must leave the authenticated launch cache intact.
    if (['/accounts/login/', '/admin/login/'].includes(url.pathname) && response.ok && !response.redirected
        && !response.headers.get('X-PWA-Scope') && response.headers.get('Content-Type')?.includes('text/html')) {
      if (navigation > lastIdentityNavigation) await clearScope(navigation);
      return response;
    }
    // Real top-level navigations use manual redirects. The worker sees an
    // opaque redirect, not the final login URL (unlike workspace fetches).
    // Check the read-only session endpoint before allowing an expired session
    // to replace a prepared local form with login and clear its page cache.
    if (response.type === 'opaqueredirect') {
      const cached = await localPage();
      if (cached) {
        const session = await fetch(new URL('/api/sync/session/', self.location.origin).href, {
          credentials: 'same-origin', cache: 'no-store', redirect: 'follow', signal: controller.signal,
        });
        const sessionUrl = sameOriginUrl(session.url);
        if (session.status === 401 || (session.redirected && sessionUrl && isAuthUrl(sessionUrl))) return cached;
      }
      return response;
    }
    const scope = response.headers.get("X-PWA-Scope");
    if (validScope(scope)) {
      if (event.resultingClientId) clientScopes.set(event.resultingClientId, scope);
      if (navigation > lastIdentityNavigation) {
        lastIdentityNavigation = navigation;
        await setActiveScope(scope);
        if (!restricted) await storeResponse(request, response, scope);
      }
    } else if (response.redirected && sameOriginUrl(response.url) && isAuthUrl(sameOriginUrl(response.url))) {
      // An expired session must not erase the working offline installation.
      return (await localPage()) || response;
    }
    if (isGatewayFailure(response)) {
      return (await localPage()) || offlineFallback(request);
    }
    return response;
  } catch {
    return (await localPage()) || offlineFallback(request);
  } finally { clearTimeout(timeout); }
}

async function staticAsset(request, url) {
  const cache = await caches.open(STATIC_CACHE).catch(() => null);
  // Precaching uses a programmatic GET. A stylesheet or script can send a
  // different Accept header even though the public file at the URL is identical.
  const cached = await cache?.match(url.href, {ignoreVary: true}).catch(() => null);
  if (cached) return cached;
  const fallback = url.search && CORE_STATIC_PATHS.has(url.pathname)
    ? await cache?.match(new URL(url.pathname, url.origin).href, {ignoreVary: true}).catch(() => null)
    : null;
  if (fallback && self.navigator?.onLine === false) return fallback;
  try {
    const response = await fetch(request);
    if (canStore(response, url, null)) await storeResponse(request, response, null);
    else if (fallback) return fallback;
    return response;
  } catch (error) {
    if (fallback) return fallback;
    throw error;
  }
}

async function cacheUrls(urls, scope) {
  // A bounded pool avoids flooding PostgreSQL with every screen at startup.
  const pending = [...new Set(urls)].map(sameOriginUrl).filter(Boolean);
  const result = { cached: [], failed: [] };
  const initialRevision = scopeRevision;
  let verifiedScope = scope && await storedScope();
  async function run() {
    while (pending.length) {
      const url = pending.shift();
      const asset = isPublicAsset(url);
      const path = url.pathname + url.search;
      if (!asset && (!validScope(scope) || !isPrivatePage(url))) continue;
      let usable = false;
      try {
        // Normal navigation still revalidates. Repeated shell requests can use
        // a recent cached copy rather than query every screen on each page load.
        const cache = await caches.open(asset ? STATIC_CACHE : `${PAGE_PREFIX}${scope}`);
        const cached = await cache.match(url.href, { ignoreVary: true });
        usable = canStore(cached, url, scope) && (asset || verifiedScope === scope);
        const age = Date.now() - Date.parse(cached?.headers.get("Date") || "");
        if (usable && (asset || (age >= 0 && age < PREFETCH_FRESH_MS))) {
          result.cached.push(path);
          continue;
        }
        const request = new Request(url.href, { credentials: "same-origin", cache: "no-cache",
          headers: asset ? {} : { "X-PWA-Scope": scope } });
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 20000);
        let response;
        try { response = await fetch(request, {signal: controller.signal}); }
        finally { clearTimeout(timer); }
        if (!canStore(response, url, scope)) {
          if (usable && isGatewayFailure(response)) result.cached.push(path);
          else result.failed.push(path);
          continue;
        }
        if (!asset && (verifiedScope !== scope || activeScope !== scope)) {
          if (scopeRevision !== initialRevision && activeScope !== scope) {
            result.failed.push(path);
            continue;
          }
          await setActiveScope(scope);
          verifiedScope = scope;
        }
        await storeResponse(request, response, scope);
        if (canStore(await cache.match(url.href, { ignoreVary: true }), url, scope)) result.cached.push(path);
        else result.failed.push(path);
      } catch {
        // A failed refresh does not remove an already prepared offline page.
        if (usable) result.cached.push(path);
        else result.failed.push(path);
      }
    }
  }
  await Promise.all([run(), run(), run()]);
  return result;
}

self.addEventListener("install", (event) => {
  // Updates wait for explicit user action or all old tabs to close.
  event.waitUntil((async () => {
    const result = await cacheUrls(CORE_ASSETS, null);
    if (result.failed.length) {
      // Keep the working previous worker/cache when a release is incomplete.
      throw new Error(`Offline assets unavailable: ${result.failed.join(', ')}`);
    }
  })());
});
self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    // Preserve verified private pages across releases, including an update
    // installed just before a long loss of connectivity.
    for (const key of keys) {
      const match = key.match(/-pages-(u\d+-b(?:\d+|all)-r[a-z_]+-s[01])$/);
      if (!match || key.startsWith(PAGE_PREFIX)) continue;
      const old = await caches.open(key);
      const target = await caches.open(`${PAGE_PREFIX}${match[1]}`);
      for (const request of await old.keys()) {
        const response = await old.match(request, {ignoreVary:true});
        if (canStore(response, sameOriginUrl(request), match[1]) && !await target.match(request, {ignoreVary:true})) {
          await target.put(request, response);
        }
      }
    }
    await Promise.all(keys.filter((key) => key.startsWith("sh-pwa-") && key !== META_CACHE
      && !key.startsWith(CACHE_VERSION) && !key.startsWith(PAGE_PREFIX)).map((key) => caches.delete(key)));
    await self.clients.claim();
  })());
});
self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = sameOriginUrl(request);
  if (!url) return;
  if (request.method === 'POST' && ['/accounts/logout/', '/admin/logout/'].includes(url.pathname)) {
    event.waitUntil(clearScope());
  }
  // A lost POST response can follow a commit: never replay a dispatched POST.
  if (request.method !== "GET") return;
  // Backup generation can exceed the page timeout. Let the browser own the
  // request and its attachment/error response; never turn it into offline HTML.
  if (url.pathname.startsWith('/settings/backups/')) return;
  if (request.mode === "navigate" || request.destination === "document" || request.headers?.get('X-Workspace-Tab') === '1') {
    event.respondWith(networkNavigation(request, event).catch(() => offlineFallback(request)));
  } else if (isPublicAsset(url)) event.respondWith(staticAsset(request, url));
});
self.addEventListener("message", (event) => {
  const message = event.data || {};
  if (message.type === "SKIP_WAITING") event.waitUntil(self.skipWaiting());
  if (message.type === "CLEAR_SCOPE") event.waitUntil(clearScope());
  if (message.type === "PWA_SCOPE" && event.source?.id && validScope(message.scope)) {
    clientScopes.set(event.source.id, message.scope);
  }
  if (message.type === "CACHE_URLS" && validScope(message.scope)) {
    const revision = scopeRevision;
    event.waitUntil((async () => {
      const metadata = await caches.open(META_CACHE);
      if (Array.isArray(message.details)) {
        await metadata.put(`/__pwa_details__/${message.scope}`, new Response(JSON.stringify(message.details)));
      }
      if (Array.isArray(message.requiredUrls)) {
        const required = message.requiredUrls.slice(0, MAX_PAGES).map(sameOriginUrl)
          .filter(url => url && isPrivatePage(url)).map(url => url.pathname + url.search);
        await metadata.put(`/__pwa_required_pages__/${message.scope}`, new Response(JSON.stringify(required)));
      }
      const assets = await cacheUrls(CORE_ASSETS, null);
      const urls = Array.isArray(message.urls) ? message.urls.slice(0, MAX_PAGES) : [];
      const pages = revision === scopeRevision || activeScope === message.scope
        ? await cacheUrls(urls, message.scope) : {cached: [], failed: urls};
      const scopeMatches = await storedScope() === message.scope;
      event.ports?.[0]?.postMessage({ cached: scopeMatches ? pages.cached : [],
        failed: [...assets.failed, ...(scopeMatches ? pages.failed : urls)] });
    })());
  }
});
self.addEventListener("sync", (event) => {
  if (event.tag !== "sh-sync-queue") return;
  event.waitUntil(self.clients.matchAll({ type: "window" }).then((clients) => {
    clients.forEach((client) => client.postMessage({ type: "PROCESS_SYNC" }));
  }));
});
