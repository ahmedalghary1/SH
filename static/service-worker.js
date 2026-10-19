// Release all shell assets together; private pages require a verified scope.
const CACHE_VERSION = "sh-pwa-v2026-10-19-receipts-05";
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const PAGE_PREFIX = `${CACHE_VERSION}-pages-`;
const META_CACHE = "sh-pwa-identity-v1";
const META_URL = "/__pwa_identity__";
const OFFLINE_URL = "/offline/";
const MAX_PAGES = 100;
const PREFETCH_FRESH_MS = 5 * 60 * 1000;
const CORE_ASSETS = [
  OFFLINE_URL, "/manifest.json", "/static/css/main.css", "/static/js/main.js",
  "/static/js/internal-tabs.js", "/static/js/orders.js", "/static/js/inventory.js",
  "/static/js/product_create.js", "/static/js/purchase_create.js", "/static/js/purchase_return.js",
  "/static/js/pwa/identity.js", "/static/js/pwa/db.js", "/static/js/pwa/sync-queue.js",
  "/static/js/pwa/sync-engine.js", "/static/js/pwa/offline-forms.js", "/static/js/pwa/offline-list-view.js",
  "/static/js/pwa/queue-view.js",
  "/static/images/sh-family-Logo.png", "/static/fonts/cairo/Cairo-400.ttf",
  "/static/fonts/cairo/Cairo-600.ttf", "/static/fonts/cairo/Cairo-700.ttf",
  "/static/icons/icon-192.png", "/static/icons/icon-512.png",
];
const clientScopes = new Map();
let activeScope;
const validScope = (value) => /^u\d+-b(?:\d+|all)-r[a-z_]+-s[01]$/.test(value || "");
const sameOriginUrl = (input) => {
  try {
    const url = new URL(typeof input === "string" ? input : input.url, self.location.origin);
    return url.origin === self.location.origin ? url : null;
  } catch { return null; }
};
const isAuthUrl = (url) => url.pathname.startsWith("/accounts/") || url.pathname.startsWith("/admin/");
const isPublicAsset = (url) => url.pathname.startsWith("/static/") || [OFFLINE_URL, "/manifest.json"].includes(url.pathname);
const isPrivatePage = (url) => !isAuthUrl(url) && !url.pathname.startsWith("/api/")
  && !url.pathname.startsWith("/media/") && !/\.(?:pdf|csv|xlsx?|zip)$/i.test(url.pathname)
  && !["export", "download", "format"].some((key) => url.searchParams.has(key));

async function readActiveScope() {
  if (activeScope !== undefined) return activeScope;
  const cache = await caches.open(META_CACHE);
  const response = await cache.match(META_URL);
  const data = await response?.json().catch(() => null);
  activeScope = validScope(data?.scope) ? data.scope : null;
  return activeScope;
}

async function setActiveScope(scope) {
  activeScope = validScope(scope) ? scope : null;
  const cache = await caches.open(META_CACHE);
  await cache.put(META_URL, new Response(JSON.stringify({ scope: activeScope }), {
    headers: { "Content-Type": "application/json" },
  }));
}

async function clearScope() {
  await setActiveScope(null);
  clientScopes.clear();
  const keys = await caches.keys();
  await Promise.all(keys.filter((key) => key.startsWith(PAGE_PREFIX)).map((key) => caches.delete(key)));
  // Pending operations remain in account-specific IndexedDB for that account.
}

function canStore(response, url, scope) {
  if (!response || !response.ok || response.type === "opaque" || response.redirected) return false;
  if ((response.headers.get("cache-control") || "").toLowerCase().includes("no-store")) return false;
  if (isPublicAsset(url)) return true;
  return isPrivatePage(url) && validScope(scope)
    && response.headers.get("X-PWA-Scope") === scope
    && response.headers.get("X-PWA-Cacheable") === "1"
    && (response.headers.get("content-type") || "").includes("text/html");
}

async function storeResponse(request, response, scope) {
  const url = sameOriginUrl(request);
  if (!url || !canStore(response, url, scope)) return;
  const name = isPublicAsset(url) ? STATIC_CACHE : `${PAGE_PREFIX}${scope}`;
  const cache = await caches.open(name);
  // Retain Vary. Ignore it only when reading this account/branch's exact URL.
  try {
    await cache.put(new Request(url.href), response.clone());
    if (name.startsWith(PAGE_PREFIX)) {
      const keys = await cache.keys();
      await Promise.all(keys.slice(0, Math.max(0, keys.length - MAX_PAGES)).map((key) => cache.delete(key)));
    }
  } catch { /* A cache/quota error must never fail a successful network GET. */ }
}

async function offlineFallback() {
  const cache = await caches.open(STATIC_CACHE);
  return (await cache.match(OFFLINE_URL)) || new Response(
    '<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>بدون اتصال — SH</title><body><main><h1>الاتصال غير متاح</h1><p>افتح الصفحة مرة أثناء الاتصال لتجهيزها للعمل بدون إنترنت. تسجيل الدخول والمزامنة يحتاجان إلى الاتصال.</p><button onclick="location.reload()">إعادة المحاولة</button></main></body></html>',
    { status: 503, headers: { "Content-Type": "text/html; charset=utf-8" } },
  );
}

async function cachedPage(request, clientId) {
  const scope = await readActiveScope();
  if (!scope || (clientScopes.has(clientId) && clientScopes.get(clientId) !== scope)) return null;
  const cache = await caches.open(`${PAGE_PREFIX}${scope}`);
  return cache.match(new Request(request.url), { ignoreVary: true });
}

async function networkNavigation(request, event) {
  const url = sameOriginUrl(request);
  if (!url) return fetch(request);
  if (isAuthUrl(url)) {
    await clearScope();
    try { return await fetch(request); } catch { return offlineFallback(); }
  }
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 8000);
  try {
    const response = await fetch(request, { signal: controller.signal });
    const scope = response.headers.get("X-PWA-Scope");
    if (validScope(scope)) {
      await setActiveScope(scope);
      if (event.resultingClientId) clientScopes.set(event.resultingClientId, scope);
      await storeResponse(request, response, scope);
    } else if (response.redirected && sameOriginUrl(response.url) && isAuthUrl(sameOriginUrl(response.url))) {
      await clearScope();
    }
    if ([502, 503, 504].includes(response.status)) {
      return (await cachedPage(request, event.clientId)) || response;
    }
    return response;
  } catch {
    return (await cachedPage(request, event.clientId)) || offlineFallback();
  } finally { clearTimeout(timeout); }
}

async function staticAsset(request) {
  const cache = await caches.open(STATIC_CACHE);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  await storeResponse(request, response, null);
  return response;
}

async function cacheUrls(urls, scope) {
  // A bounded pool avoids flooding PostgreSQL with every screen at startup.
  const pending = [...new Set(urls)].map(sameOriginUrl).filter(Boolean);
  async function run() {
    while (pending.length) {
      const url = pending.shift();
      if (!isPublicAsset(url) && (!validScope(scope) || !isPrivatePage(url))) continue;
      try {
        // Normal navigation still revalidates. Repeated shell requests can use
        // a recent cached copy rather than query every screen on each page load.
        const cache = await caches.open(isPublicAsset(url) ? STATIC_CACHE : `${PAGE_PREFIX}${scope}`);
        const cached = await cache.match(url.href, { ignoreVary: true });
        const age = Date.now() - Date.parse(cached?.headers.get("Date") || "");
        if (cached && (isPublicAsset(url) || (age >= 0 && age < PREFETCH_FRESH_MS))) continue;
        const request = new Request(url.href, { credentials: "same-origin", cache: "no-cache",
          headers: !isPublicAsset(url) ? { "X-PWA-Scope": scope } : {} });
        const response = await fetch(request);
        if (!isPublicAsset(url) && response.headers.get("X-PWA-Scope") !== scope) continue;
        if (!isPublicAsset(url)) await setActiveScope(scope);
        await storeResponse(request, response, scope);
      } catch { /* Failures are isolated per URL. */ }
    }
  }
  await Promise.all([run(), run(), run()]);
}

self.addEventListener("install", (event) => {
  // Updates wait for explicit user action or all old tabs to close.
  event.waitUntil(cacheUrls(CORE_ASSETS, null));
});
self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((key) => key.startsWith("sh-pwa-") && key !== META_CACHE
      && !key.startsWith(CACHE_VERSION)).map((key) => caches.delete(key)));
    await self.clients.claim();
  })());
});
self.addEventListener("fetch", (event) => {
  const request = event.request;
  // A lost POST response can follow a commit: never replay a dispatched POST.
  if (request.method !== "GET") return;
  const url = sameOriginUrl(request);
  if (!url) return;
  if (request.mode === "navigate" || request.destination === "document") {
    event.respondWith(networkNavigation(request, event));
  } else if (isPublicAsset(url)) event.respondWith(staticAsset(request));
});
self.addEventListener("message", (event) => {
  const message = event.data || {};
  if (message.type === "SKIP_WAITING") event.waitUntil(self.skipWaiting());
  if (message.type === "CLEAR_SCOPE") event.waitUntil(clearScope());
  if (message.type === "PWA_SCOPE" && event.source?.id && validScope(message.scope)) {
    clientScopes.set(event.source.id, message.scope);
  }
  if (message.type === "CACHE_URLS" && validScope(message.scope)) {
    event.waitUntil(cacheUrls(Array.isArray(message.urls) ? message.urls.slice(0, MAX_PAGES) : [], message.scope));
  }
});
self.addEventListener("sync", (event) => {
  if (event.tag !== "sh-sync-queue") return;
  event.waitUntil(self.clients.matchAll({ type: "window" }).then((clients) => {
    clients.forEach((client) => client.postMessage({ type: "PROCESS_SYNC" }));
  }));
});
