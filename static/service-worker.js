const CACHE_VERSION = "sh-pwa-v2026-07-02-02";
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
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png"
];

const APP_SHELL_PAGES = [
  "/products/",
  "/inventory/stock/",
  "/customers/",
  "/orders/create/",
  "/orders/",
  "/finance/cash/",
  "/returns/",
  "/sales-reps/"
];

const CACHEABLE_DESTINATIONS = new Set(["document", "style", "script", "image", "font"]);
const CACHEABLE_EXTENSIONS = /\.(?:css|js|png|jpg|jpeg|gif|webp|svg|ico|woff2?|ttf)$/i;

function isApiRequest(url) {
  return url.pathname.startsWith("/api/");
}

function isCacheableGet(request) {
  if (request.method !== "GET") return false;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return false;
  if (isApiRequest(url)) return false;
  return CACHEABLE_DESTINATIONS.has(request.destination) || CACHEABLE_EXTENSIONS.test(url.pathname);
}

async function putInCache(cacheName, request, response) {
  if (!response || response.status >= 400) return;
  const cache = await caches.open(cacheName);
  await cache.put(request, response.clone());
}

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) {
    fetch(request)
      .then((response) => putInCache(request.destination === "document" ? PAGE_CACHE : STATIC_CACHE, request, response))
      .catch(() => {});
    return cached;
  }

  try {
    const response = await fetch(request);
    await putInCache(request.destination === "document" ? PAGE_CACHE : STATIC_CACHE, request, response);
    return response;
  } catch (error) {
    if (request.mode === "navigate" || request.destination === "document") {
      return caches.match(OFFLINE_URL);
    }
    throw error;
  }
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then((cache) => Promise.allSettled([...CORE_ASSETS, ...APP_SHELL_PAGES].map((url) => cache.add(url))))
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

  if (request.mode === "navigate") {
    event.respondWith(cacheFirst(request));
    return;
  }

  if (isCacheableGet(request)) {
    event.respondWith(cacheFirst(request));
  }
});

self.addEventListener("message", (event) => {
  if (event.data?.type === "SKIP_WAITING") {
    self.skipWaiting();
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
