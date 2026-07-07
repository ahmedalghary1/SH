const CACHE_VERSION = "sh-pwa-v2026-07-07-unsaved-forms-01";
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const PAGE_CACHE = `${CACHE_VERSION}-pages`;
const OFFLINE_URL = "/offline/";
const DB_NAME = "sh-offline-db";
const DB_VERSION = 2;
const MAX_OFFLINE_FILE_BYTES = 5 * 1024 * 1024;

const CORE_ASSETS = [
  "/",
  OFFLINE_URL,
  "/manifest.json",
  "/static/css/main.css",
  "/static/js/main.js",
  "/static/js/orders.js",
  "/static/js/inventory.js",
  "/static/js/product_create.js",
  "/static/js/purchase_create.js",
  "/static/js/purchase_return.js",
  "/static/js/pwa/db.js",
  "/static/js/pwa/sync-queue.js",
  "/static/js/pwa/sync-engine.js",
  "/static/js/pwa/offline-forms.js",
  "/static/js/pwa/offline-list-view.js",
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
  "/products/categories/create/",
  "/products/sizes/",
  "/products/sizes/create/",
  "/products/colors/",
  "/products/colors/create/",
  "/products/variants/create/",
  "/products/bulk-price-update/",
  "/inventory/stock/",
  "/inventory/movements/",
  "/inventory/movements/in/",
  "/inventory/movements/out/",
  "/inventory/movements/transfer/",
  "/inventory/movements/representative-issue/",
  "/inventory/movements/representative-return/",
  "/inventory/movements/adjustment/",
  "/inventory/warehouses/",
  "/inventory/warehouses/create/",
  "/customers/",
  "/customers/simple/create/",
  "/customers/list/",
  "/customers/create/",
  "/orders/create/",
  "/orders/",
  "/orders/quotes/",
  "/invoices/",
  "/finance/cash/",
  "/finance/shift/",
  "/finance/accounts/",
  "/finance/accounts/create/",
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
  "/sales-reps/assign/",
  "/sales-reps/return-stock/",
  "/sales-reps/record-sale/",
  "/sales-reps/collection/",
  "/sales-reps/handover/",
  "/sales-reps/statement/",
  "/purchases/suppliers/simple/",
  "/purchases/suppliers/simple/create/",
  "/purchases/suppliers/",
  "/purchases/suppliers/create/",
  "/purchases/suppliers/raw-purchase/",
  "/purchases/orders/",
  "/purchases/orders/create/",
  "/purchases/orders/return/",
  "/reports/",
  "/settings/"
];

const CACHEABLE_DESTINATIONS = new Set(["document", "style", "script", "image", "font", "manifest"]);
const STATIC_EXTENSIONS = /\.(?:css|js|json|png|jpg|jpeg|gif|webp|svg|ico|woff2?|ttf)$/i;
const STORE_NAMES = {
  sales: "sales",
  customers: "customers",
  products: "products",
  productVariants: "product_variants",
  stock: "stock",
  warehouses: "warehouses",
  stockMovements: "stock_movements",
  cashAccounts: "cash_accounts",
  cashTransactions: "cash_transactions",
  driverActions: "driver_actions",
  syncQueue: "sync_queue",
  metadata: "metadata",
};
const ENTITY_STORE = {
  sales: STORE_NAMES.sales,
  returns: STORE_NAMES.sales,
  customers: STORE_NAMES.customers,
  products: STORE_NAMES.products,
  stock: STORE_NAMES.stockMovements,
  cash: STORE_NAMES.cashTransactions,
  driver_actions: STORE_NAMES.driverActions,
};
const SERVER_ENTITY_PREFIX = {
  sales: "order",
  returns: "return",
  customers: "customer",
  products: "product",
  stock: "stock",
  cash: "payment",
  driver_actions: "driver_action",
  purchases: "purchase",
};
let swDbPromise = null;
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

function uuid() {
  if (self.crypto?.randomUUID) return self.crypto.randomUUID();
  return "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (char) => {
    const value = Number(char) ^ (self.crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (Number(char) / 4)));
    return value.toString(16);
  });
}

function nowIso() {
  return new Date().toISOString();
}

function createStore(db, name, options = { keyPath: "id" }) {
  if (!db.objectStoreNames.contains(name)) {
    return db.createObjectStore(name, options);
  }
  return null;
}

function createIndexIfMissing(store, name, keyPath, options = { unique: false }) {
  if (store && !store.indexNames.contains(name)) {
    store.createIndex(name, keyPath, options);
  }
}

function addEntityIndexes(store) {
  createIndexIfMissing(store, "sync_status", "sync_status");
  createIndexIfMissing(store, "updated_at", "updated_at");
  createIndexIfMissing(store, "server_id", "server_id");
}

function openOfflineDB() {
  if (swDbPromise) return swDbPromise;
  swDbPromise = new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      [
        STORE_NAMES.sales,
        STORE_NAMES.customers,
        STORE_NAMES.products,
        STORE_NAMES.productVariants,
        STORE_NAMES.stock,
        STORE_NAMES.warehouses,
        STORE_NAMES.stockMovements,
        STORE_NAMES.cashAccounts,
        STORE_NAMES.cashTransactions,
        STORE_NAMES.driverActions,
      ].forEach((storeName) => addEntityIndexes(createStore(db, storeName)));

      const queue = createStore(db, STORE_NAMES.syncQueue);
      createIndexIfMissing(queue, "status", "status");
      createIndexIfMissing(queue, "entity_name", "entity_name");
      createIndexIfMissing(queue, "timestamp", "timestamp");
      createIndexIfMissing(queue, "next_attempt_at", "next_attempt_at");
      createStore(db, STORE_NAMES.metadata, { keyPath: "key" });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => {
      swDbPromise = null;
      reject(request.error);
    };
    request.onblocked = () => {
      swDbPromise = null;
      reject(new Error("Offline database upgrade is blocked by an open tab."));
    };
  });
  return swDbPromise;
}

function transactionDone(tx) {
  return new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error);
  });
}

function withRecordMeta(record, operationType = "create", syncStatus = "pending") {
  const timestamp = nowIso();
  return {
    id: record.id || record.local_uuid || uuid(),
    created_at: record.created_at || timestamp,
    updated_at: record.updated_at || timestamp,
    sync_status: record.sync_status || syncStatus,
    operation_type: record.operation_type || operationType,
    ...record,
  };
}

function storeForEntity(entityName) {
  return ENTITY_STORE[entityName] || STORE_NAMES.syncQueue;
}

function appendValue(target, key, value) {
  if (Object.prototype.hasOwnProperty.call(target, key)) {
    target[key] = Array.isArray(target[key]) ? [...target[key], value] : [target[key], value];
  } else {
    target[key] = value;
  }
}

async function fileToPayload(file) {
  if (!file || !file.size) return null;
  if (file.size > MAX_OFFLINE_FILE_BYTES) {
    throw new Error(`File ${file.name} is larger than 5 MB and cannot be saved offline.`);
  }
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return {
    name: file.name,
    type: file.type || "application/octet-stream",
    size: file.size,
    last_modified: file.lastModified || null,
    data: btoa(binary),
  };
}

async function formDataToObject(formData) {
  const data = {};
  const files = {};
  const fileTasks = [];
  formData.forEach((value, key) => {
    if (typeof File !== "undefined" && value instanceof File) {
      fileTasks.push(fileToPayload(value).then((payload) => {
        if (payload) appendValue(files, key, payload);
      }));
      return;
    }
    appendValue(data, key, value);
  });
  await Promise.all(fileTasks);
  if (Object.keys(files).length) data._files = files;
  return data;
}

async function requestPayloadToFields(request) {
  const contentType = request.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return request.clone().json().catch(() => ({}));
  }
  return formDataToObject(await request.clone().formData());
}

function serverIdFromPath(path) {
  const match = String(path || "").match(/\/(\d+)(?:\/|$)/);
  return match ? match[1] : "";
}

function localUuidFor(classification, serverId) {
  if (!serverId) return uuid();
  const prefix = SERVER_ENTITY_PREFIX[classification.entity_name] || classification.entity_type || classification.entity_name;
  return `server-${prefix}-${serverId}`;
}

function operationTypeForPath(path) {
  if (path.includes("/delete/") || path.includes("/deactivate/") || path.includes("delete")) return "delete";
  if (
    path.includes("/update/")
    || path.includes("/edit/")
    || path.includes("/status/")
    || path.includes("/confirm/")
    || path.includes("/cancel/")
    || path.includes("/return/")
    || path.includes("/approve/")
    || path.includes("/reject/")
    || path.includes("/complete/")
  ) return "update";
  return "create";
}

function classifyMutationPath(path) {
  if (path.startsWith("/orders/")) return { entity_name: "sales", entity_type: "order", action_type: "create_invoice" };
  if (path.startsWith("/invoices/") && path.includes("/payments/add/")) return { entity_name: "cash", entity_type: "payment", action_type: "cash_transaction" };
  if (path.includes("/interactions/")) return null;
  if (path.startsWith("/customers/")) return { entity_name: "customers", entity_type: "customer", action_type: "save_customer" };
  if (path.startsWith("/inventory/warehouses/")) return { entity_name: "stock", entity_type: "stock", action_type: "save_warehouse" };
  if (path.startsWith("/inventory/movements/")) return { entity_name: "stock", entity_type: "stock", action_type: "stock_movement" };
  if (path.startsWith("/finance/accounts/")) return { entity_name: "cash", entity_type: "payment", action_type: "save_cash_account" };
  if (path.startsWith("/finance/transactions/")) return { entity_name: "cash", entity_type: "payment", action_type: "cash_transaction" };
  if (path.startsWith("/sales-reps/")) return { entity_name: "driver_actions", entity_type: "driver_action", action_type: "driver_action" };
  if (path.startsWith("/returns/")) return { entity_name: "returns", entity_type: "return", action_type: "sales_return" };
  if (path.startsWith("/products/")) return { entity_name: "products", entity_type: "product", action_type: "save_product" };
  if (path.startsWith("/purchases/")) return { entity_name: "purchases", entity_type: "purchase", action_type: "purchase_action" };
  return null;
}

function parseItems(value) {
  try {
    const parsed = JSON.parse(value || "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch (error) {
    return [];
  }
}

function customerPayload(fields, localUuid, serverId = "") {
  return {
    id: localUuid,
    local_uuid: localUuid,
    server_id: serverId || fields.server_id || "",
    customer: {
      local_uuid: localUuid,
      server_id: serverId || fields.server_id || "",
      name: fields.name || fields.customer_name || "",
      phone: fields.phone || "",
      whatsapp: fields.whatsapp || "",
      customer_type: fields.customer_type || "retail",
      address: fields.address || "",
      credit_limit: fields.credit_limit || "0",
      opening_balance: fields.opening_balance || "0",
      notes: fields.notes || "",
      sales_representative: fields.sales_representative || "",
      updated_at: nowIso(),
    },
    name: fields.name || fields.customer_name || "",
    phone: fields.phone || "",
    customer_type: fields.customer_type || "retail",
    address: fields.address || "",
    opening_balance: fields.opening_balance || "0",
    updated_at: nowIso(),
  };
}

function statusForOrderPath(path, fields = {}) {
  if (fields.status) return fields.status;
  if (path.includes("/confirm/")) return "confirmed";
  if (path.includes("/cancel/")) return "cancelled";
  if (path.includes("/return/")) return "returned";
  return "";
}

function orderPayload(fields, path, localUuid, serverId = "") {
  const items = parseItems(fields.items_json);
  return {
    id: localUuid,
    local_uuid: localUuid,
    server_id: serverId || fields.server_id || "",
    order: {
      local_uuid: localUuid,
      server_id: serverId || fields.server_id || "",
      customer_server_id: /^\d+$/.test(String(fields.customer || "")) ? fields.customer : "",
      customer_local_uuid: /^\d+$/.test(String(fields.customer || "")) ? "" : fields.customer || "",
      document_type: fields.document_type || "sale",
      order_type: fields.order_type || "b2c",
      payment_method: fields.payment_method || "cash",
      warehouse: fields.warehouse || "",
      status: statusForOrderPath(path, fields),
      paid_amount: fields.paid_amount || "0",
      discount: fields.discount_amount || "0",
      discount_amount: fields.discount_amount || "0",
      discount_percentage: fields.discount_percentage || "0",
      notes: fields.notes || "",
      action: fields.action || "confirm",
      updated_at: nowIso(),
    },
    items: items.map((item) => ({
      ...item,
      variant_server_id: item.variant_server_id || item.variant_id,
      warehouse_server_id: item.warehouse_server_id || item.warehouse_id,
    })),
    form: fields,
    original_url: path,
    updated_at: nowIso(),
  };
}

function genericPayload(fields, path, localUuid, entityType, serverId = "") {
  return {
    id: localUuid,
    local_uuid: localUuid,
    server_id: serverId || fields.server_id || "",
    [entityType]: {
      ...fields,
      local_uuid: localUuid,
      server_id: serverId || fields.server_id || "",
      updated_at: nowIso(),
    },
    form: fields,
    original_url: path,
    updated_at: nowIso(),
  };
}

function payloadForMutation(classification, fields, path, localUuid, serverId) {
  if (classification.entity_name === "customers") return customerPayload(fields, localUuid, serverId);
  if (classification.entity_name === "sales") return orderPayload(fields, path, localUuid, serverId);
  return genericPayload(fields, path, localUuid, classification.entity_type, serverId);
}

async function queueEntityOperation(entityName, actionType, payload, options = {}) {
  const timestamp = nowIso();
  const storeName = storeForEntity(entityName);
  const localRecordId = payload.id || payload.local_uuid || uuid();
  const localRecord = storeName !== STORE_NAMES.syncQueue
    ? withRecordMeta(
      {
        ...payload,
        id: localRecordId,
        local_uuid: payload.local_uuid || localRecordId,
      },
      options.operation_type || "create",
      "pending"
    )
    : null;
  const queueItem = withRecordMeta(
    {
      id: uuid(),
      action_type: actionType,
      entity_name: entityName,
      entity_type: options.entity_type,
      operation_type: options.operation_type || "create",
      payload: {
        ...payload,
        local_uuid: localRecord?.local_uuid || payload.local_uuid,
        updated_at: localRecord?.updated_at || payload.updated_at || timestamp,
      },
      local_uuid: localRecord?.local_uuid || payload.local_uuid || localRecordId,
      local_record_id: localRecord?.id || payload.id || null,
      timestamp,
      status: "pending",
      attempts: 0,
      next_attempt_at: timestamp,
      idempotency_key: uuid(),
      sync_status: "pending",
    },
    "create",
    "pending"
  );

  const db = await openOfflineDB();
  const stores = localRecord && storeName !== STORE_NAMES.syncQueue
    ? [storeName, STORE_NAMES.syncQueue]
    : [STORE_NAMES.syncQueue];
  const tx = db.transaction(stores, "readwrite");
  if (localRecord && storeName !== STORE_NAMES.syncQueue) {
    tx.objectStore(storeName).put(localRecord);
  }
  tx.objectStore(STORE_NAMES.syncQueue).put(queueItem);
  await transactionDone(tx);
  return queueItem;
}

async function queuePostRequest(request) {
  const url = sameOriginUrl(request);
  if (!url) return false;
  const classification = classifyMutationPath(url.pathname);
  if (!classification) return false;

  const fields = await requestPayloadToFields(request);
  const serverId = serverIdFromPath(url.pathname);
  const localUuid = localUuidFor(classification, serverId);
  const payload = payloadForMutation(classification, fields, url.pathname, localUuid, serverId);
  payload.source = "pwa-service-worker";
  payload.original_url = url.pathname;
  payload.server_id = serverId || payload.server_id || "";

  const queueItem = await queueEntityOperation(classification.entity_name, classification.action_type, payload, {
    entity_type: classification.entity_type,
    operation_type: operationTypeForPath(url.pathname),
  });
  await self.registration.sync?.register("sh-sync-queue").catch(() => {});
  return {
    queued: true,
    queueItem,
    classification,
    fields,
    payload,
    path: url.pathname,
    local_uuid: queueItem.local_uuid || localUuid,
  };
}

function isApiRequest(url) {
  return url.pathname.startsWith("/api/");
}

function isAuthRequest(url) {
  return url.pathname.startsWith("/accounts/") || url.pathname.startsWith("/admin/");
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
  if (!url || isApiRequest(url) || isAuthRequest(url)) return false;
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
  const requestUrl = sameOriginUrl(cacheRequest);
  if (requestUrl && isAuthRequest(requestUrl)) return false;
  if (response.headers.has("set-cookie")) return false;
  const cacheControl = (response.headers.get("cache-control") || "").toLowerCase();
  if (cacheControl.includes("no-store") || cacheControl.includes("private")) return false;

  if (response.redirected && response.url) {
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

async function networkFirstNavigation(request) {
  const url = sameOriginUrl(request);
  if (url && isAuthRequest(url)) {
    return fetch(request);
  }

  try {
    const response = await fetch(request);
    await putInCache(PAGE_CACHE, request, response);
    return response;
  } catch (error) {
    const cached = await matchCachedRequest(request);
    if (cached) return cached;
    return navigationFallback();
  }
}

function shouldHandlePost(request) {
  if (request.method !== "POST") return false;
  const url = sameOriginUrl(request);
  if (!url || isApiRequest(url)) return false;
  if (url.pathname.startsWith("/accounts/") || url.pathname.startsWith("/admin/")) return false;
  return true;
}

function wantsJsonResponse(request) {
  const accept = request.headers.get("accept") || "";
  const requestedWith = request.headers.get("x-requested-with") || "";
  return accept.includes("application/json")
    || requestedWith.toLowerCase() === "xmlhttprequest"
    || (!isNavigationRequest(request) && request.destination === "");
}

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json; charset=UTF-8" },
  });
}

function offlineJsonDataForMutation(result) {
  const path = result.path || "";
  const fields = result.fields || {};
  const localUuid = result.local_uuid || result.payload?.local_uuid || uuid();
  const name = fields.name
    || fields.new_supplier_name
    || fields.new_product_name
    || fields.customer_name
    || "Offline item";

  if (path.includes("/quick-create-category/")) {
    return { id: localUuid, local_uuid: localUuid, name: fields.name || name, offline: true };
  }
  if (path.includes("/quick-create-color/")) {
    return {
      id: localUuid,
      local_uuid: localUuid,
      name: fields.name || name,
      hex_code: fields.hex_code || "",
      offline: true,
    };
  }
  if (path.includes("/quick-create-size/")) {
    return { id: localUuid, local_uuid: localUuid, name: fields.name || name, offline: true };
  }
  if (path.includes("/quick-create-warehouse/")) {
    return {
      id: localUuid,
      local_uuid: localUuid,
      name: fields.name || fields.new_warehouse_name || name,
      warehouse_type: fields.warehouse_type || "main",
      offline: true,
    };
  }
  if (path.includes("/quick-create-supplier/")) {
    return {
      id: localUuid,
      local_uuid: localUuid,
      name: fields.new_supplier_name || fields.name || name,
      phone: fields.new_supplier_phone || fields.phone || "",
      offline: true,
    };
  }
  if (path.includes("/quick-create-product/")) {
    const productName = fields.new_product_name || fields.name || name;
    const sku = fields.new_product_sku || fields.sku || `offline-${localUuid}`;
    return {
      id: localUuid,
      local_uuid: localUuid,
      name: productName,
      sku,
      pieces_per_dozen: fields.pieces_per_dozen || "12",
      offline: true,
    };
  }
  return { id: localUuid, local_uuid: localUuid, name, offline: true };
}

function redirectAfterOfflineSave(request) {
  const target = request.referrer ? sameOriginUrl(request.referrer) : sameOriginUrl(request);
  const url = target || new URL("/", self.location.origin);
  url.hash = "";
  url.searchParams.set("offline_saved", "1");
  return Response.redirect(url.href, 303);
}

async function postOfflineResponse(request, error) {
  try {
    const result = await queuePostRequest(request);
    if (result?.queued) {
      if (wantsJsonResponse(request)) {
        return jsonResponse({
          success: true,
          offline: true,
          queued: true,
          message: "Saved offline and queued for sync.",
          data: offlineJsonDataForMutation(result),
        });
      }
      return redirectAfterOfflineSave(request);
    }
  } catch (queueError) {
    if (wantsJsonResponse(request)) {
      return jsonResponse({
        success: false,
        offline: true,
        error: String(queueError.message || queueError),
      }, 503);
    }
  }

  if (isNavigationRequest(request)) return navigationFallback();
  throw error;
}

async function networkFirstPost(request) {
  try {
    return await fetch(request.clone());
  } catch (error) {
    return postOfflineResponse(request, error);
  }
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    cacheUrls(CORE_ASSETS)
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

  if (shouldHandlePost(request)) {
    event.respondWith(networkFirstPost(request));
    return;
  }

  if (isNavigationRequest(request)) {
    if (request.method !== "GET") return;
    event.respondWith(networkFirstNavigation(request));
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
