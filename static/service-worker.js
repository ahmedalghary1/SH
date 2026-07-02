const CACHE_VERSION = "sh-pwa-v2026-07-02-05";
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const PAGE_CACHE = `${CACHE_VERSION}-pages`;
const OFFLINE_URL = "/offline/";

const CORE_ASSETS = [
  "/",
  OFFLINE_URL,
  "/manifest.json",
  "/static/css/main.css",
  "/static/js/main.js",
  "/static/js/orders.js",
  "/static/js/inventory.js",
  "/static/js/pwa/db.js",
  "/static/js/pwa/sync-queue.js",
  "/static/js/pwa/sync-engine.js",
  "/static/js/pwa/offline-forms.js",
  "/static/images/sh-family-Logo.png",
  "/static/fonts/cairo/Cairo-400.ttf",
  "/static/fonts/cairo/Cairo-600.ttf",
  "/static/fonts/cairo/Cairo-700.ttf",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png"
];

const APP_SHELL_PAGES = [
  "/",
  "/products/",
  "/products/create/",
  "/products/categories/",
  "/products/sizes/",
  "/products/colors/",
  "/inventory/stock/",
  "/inventory/movements/",
  "/inventory/movements/in/",
  "/inventory/movements/out/",
  "/inventory/movements/transfer/",
  "/inventory/movements/representative-issue/",
  "/inventory/movements/representative-return/",
  "/inventory/movements/adjustment/",
  "/inventory/warehouses/",
  "/customers/",
  "/customers/simple/create/",
  "/customers/list/",
  "/orders/create/",
  "/orders/",
  "/orders/quotes/",
  "/invoices/",
  "/finance/cash/",
  "/finance/shift/",
  "/finance/accounts/",
  "/finance/transactions/",
  "/finance/transactions/expense/",
  "/finance/transactions/collection/",
  "/finance/transactions/supplier-payment/",
  "/finance/transactions/transfer/",
  "/returns/",
  "/returns/simple/",
  "/returns/exchange/",
  "/returns/create/",
  "/sales-reps/",
  "/sales-reps/assignments/",
  "/sales-reps/record-sale/",
  "/sales-reps/collection/",
  "/sales-reps/statement/",
  "/purchases/suppliers/simple/",
  "/purchases/orders/",
  "/purchases/orders/create/",
  "/purchases/orders/return/",
  "/reports/",
  "/settings/"
];

const CACHEABLE_DESTINATIONS = new Set(["document", "style", "script", "image", "font", "manifest"]);
const STATIC_EXTENSIONS = /\.(?:css|js|json|png|jpg|jpeg|gif|webp|svg|ico|woff2?|ttf)$/i;
const OFFLINE_RESPONSE_HTML = `<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SH Offline</title>
  <style>
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; font-family: Arial, sans-serif; background: #f7f9fc; color: #123c69; }
    main { max-width: 460px; padding: 24px; text-align: center; }
    h1 { margin: 0 0 10px; font-size: 26px; }
    p { margin: 0; line-height: 1.7; color: #334155; }
  </style>
</head>
<body>
  <main>
    <h1>Offline mode</h1>
    <p>The requested page is not cached yet. Open it once while online, then it will work without internet.</p>
  </main>
</body>
</html>`;

function unique(values) {
  return [...new Set(values.filter(Boolean))];
}

function sameOriginUrl(input) {
  try {
    const url = new URL(typeof input === "string" ? input : input.url, self.location.origin);
    return url.origin === self.location.origin ? url : null;
  } catch (error) {
    return null;
  }
}

function isApiRequest(url) {
  return url.pathname.startsWith("/api/");
}

function isNavigationRequest(request) {
  return request.mode === "navigate" || request.destination === "document";
}

function isShellPageUrl(url) {
  return !STATIC_EXTENSIONS.test(url.pathname);
}

function isCacheableGet(request) {
  if (request.method !== "GET") return false;
  const url = sameOriginUrl(request);
  if (!url || isApiRequest(url)) return false;
  return CACHEABLE_DESTINATIONS.has(request.destination) || STATIC_EXTENSIONS.test(url.pathname);
}

function normalizedRequest(input, stripSearch = false) {
  const url = sameOriginUrl(input);
  if (!url) return null;
  url.hash = "";
  if (stripSearch) url.search = "";
  return new Request(url.href, { credentials: "include" });
}

function shouldStoreResponse(cacheRequest, response) {
  if (!cacheRequest || !response || !response.ok || response.type !== "basic") return false;

  if (response.redirected && response.url) {
    const requestUrl = sameOriginUrl(cacheRequest);
    const responseUrl = sameOriginUrl(response.url);
    if (!requestUrl || !responseUrl || requestUrl.pathname !== responseUrl.pathname) {
      return false;
    }
  }

  return true;
}

function cloneForCache(response) {
  const headers = new Headers(response.headers);
  headers.delete("set-cookie");
  headers.delete("vary");
  return new Response(response.clone().body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

async function putInCache(cacheName, request, response) {
  const stripSearch = isNavigationRequest(request) || isShellPageUrl(sameOriginUrl(request) || new URL(self.location.href));
  const cacheRequest = normalizedRequest(request, stripSearch);
  if (!shouldStoreResponse(cacheRequest, response)) return false;
  const cache = await caches.open(cacheName);
  await cache.put(cacheRequest, cloneForCache(response));
  return true;
}

async function ensureOfflineFallback() {
  const cached = await caches.match(OFFLINE_URL);
  if (cached) return;
  const cache = await caches.open(PAGE_CACHE);
  await cache.put(
    normalizedRequest(OFFLINE_URL, true),
    new Response(OFFLINE_RESPONSE_HTML, {
      headers: { "Content-Type": "text/html; charset=UTF-8" },
    })
  );
}

async function cacheUrls(urls) {
  const jobs = unique(urls).map(async (urlValue) => {
    const url = sameOriginUrl(urlValue);
    if (!url || isApiRequest(url)) return;

    const isPage = isShellPageUrl(url);
    const request = new Request(url.href, {
      credentials: "include",
      cache: "reload",
    });
    const response = await fetch(request);
    await putInCache(isPage ? PAGE_CACHE : STATIC_CACHE, request, response);
  });

  await Promise.allSettled(jobs);
  await ensureOfflineFallback();
}

async function matchCachedRequest(request) {
  const exact = await caches.match(request);
  if (exact) return exact;

  if (isNavigationRequest(request)) {
    const normalized = normalizedRequest(request, true);
    if (normalized) {
      const byPath = await caches.match(normalized);
      if (byPath) return byPath;
    }
  }

  return null;
}

async function navigationFallback() {
  for (const url of ["/", OFFLINE_URL]) {
    const cached = await caches.match(normalizedRequest(url, true));
    if (cached) return cached;
  }

  return new Response(OFFLINE_RESPONSE_HTML, {
    headers: { "Content-Type": "text/html; charset=UTF-8" },
  });
}

function refreshInBackground(request) {
  fetch(request)
    .then((response) => putInCache(isNavigationRequest(request) ? PAGE_CACHE : STATIC_CACHE, request, response))
    .catch(() => {});
}

async function cacheFirst(request) {
  const cached = await matchCachedRequest(request);
  if (cached) {
    refreshInBackground(request);
    return cached;
  }

  try {
    const response = await fetch(request);
    await putInCache(isNavigationRequest(request) ? PAGE_CACHE : STATIC_CACHE, request, response);
    return response;
  } catch (error) {
    if (isNavigationRequest(request)) {
      return navigationFallback();
    }
    throw error;
  }
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    cacheUrls([...CORE_ASSETS, ...APP_SHELL_PAGES])
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => !key.startsWith(CACHE_VERSION)).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;

  if (isNavigationRequest(request)) {
    if (request.method !== "GET") return;
    event.respondWith(cacheFirst(request));
    return;
  }

  if (isCacheableGet(request)) {
    event.respondWith(cacheFirst(request));
  }
});

self.addEventListener("message", (event) => {
  if (event.data?.type === "SKIP_WAITING") {
    event.waitUntil(self.skipWaiting());
    return;
  }

  if (event.data?.type === "CACHE_URLS") {
    const urls = Array.isArray(event.data.urls) ? event.data.urls : [];
    event.waitUntil(cacheUrls(urls));
  }
});

self.addEventListener("sync", (event) => {
  if (event.tag !== "sh-sync-queue") return;
  event.waitUntil(
    self.clients.matchAll({ includeUncontrolled: true, type: "window" }).then((clients) => {
      clients.forEach((client) => client.postMessage({ type: "PROCESS_SYNC" }));
    })
  );
});
