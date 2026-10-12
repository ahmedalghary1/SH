import {
    getDeviceId,
    getAll,
    getDueQueueItems,
    importBootstrap,
    markLocalEntitySynced,
    markQueueItemFailed,
    nowIso,
    removeQueueItem,
    setMetadata,
    STORE_NAMES,
} from "./db.js";
import { getOfflineScope } from "./identity.js";

const ENDPOINTS = {
    sales: "/api/sync/sales/",
    returns: "/api/sync/returns/",
    customers: "/api/sync/customers/",
    products: "/api/sync/products/",
    stock: "/api/sync/stock/",
    cash: "/api/sync/cash/",
    driver_actions: "/api/sync/driver-actions/",
    purchases: "/api/sync/purchases/",
};

const DEFAULT_ENTITY_TYPES = {
    sales: "order",
    returns: "return",
    customers: "customer",
    products: "product",
    stock: "stock",
    cash: "payment",
    driver_actions: "driver_action",
    purchases: "purchase",
};

const APP_SHELL_URLS = [
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
    "/finance/transactions/?type=customer_payment",
    "/finance/transactions/?type=expense",
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
    "/settings/",
];

let syncInProgress = false;
let bootstrapInProgress = false;
let csrfToken = null;
let shellCached = false;
let lastBootstrapAt = 0;

function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== "") {
        const cookies = document.cookie.split(";");
        for (let i = 0; i < cookies.length; i += 1) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === `${name}=`) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

function syncStatusEvent(detail) {
    window.dispatchEvent(new CustomEvent("sh-sync-status", { detail }));
}

function uniqueUrls(urls) {
    const seen = new Set();
    return urls
        .filter(Boolean)
        .map((url) => new URL(url, window.location.origin))
        .filter((url) => url.origin === window.location.origin)
        .map((url) => {
            url.hash = "";
            return `${url.pathname}${url.search}`;
        })
        .filter((url) => {
            if (seen.has(url)) return false;
            seen.add(url);
            return true;
        });
}

export async function cacheAppShell(extraUrls = []) {
    const scope = getOfflineScope();
    if (!("serviceWorker" in navigator) || !scope || !navigator.onLine) return;
    const urls = uniqueUrls([
        ...(shellCached ? [] : APP_SHELL_URLS.filter((url) => !["/reports/", "/settings/"].includes(url))),
        `${window.location.pathname}${window.location.search}`,
        ...extraUrls,
    ]);
    if (!urls.length) return;

    try {
        // Don't wait forever on a browser where worker installation is disabled.
        const registration = await navigator.serviceWorker.getRegistration("/");
        if (!registration) return;
        const worker = navigator.serviceWorker.controller || registration.active || registration.waiting || registration.installing;
        worker?.postMessage({ type: "PWA_SCOPE", scope });
        worker?.postMessage({ type: "CACHE_URLS", urls, scope });
        if (worker) shellCached = true;
    } catch (error) {
        syncStatusEvent({ state: "app_shell_cache_failed", error: String(error.message || error) });
    }
}

async function jsonFetch(url, options = {}) {
    const headers = {
        Accept: "application/json",
        ...options.headers,
    };
    if (!(options.body instanceof FormData) && !headers["Content-Type"]) {
        headers["Content-Type"] = "application/json";
    }
    const scope = getOfflineScope();
    if (!scope) throw new Error("سجّل الدخول قبل المزامنة.");
    headers["X-PWA-Scope"] = scope;
    const csrf = csrfToken || getCookie("csrftoken");
    if (csrf) headers["X-CSRFToken"] = csrf;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 15000);
    let response;
    try { response = await fetch(url, {
        credentials: "same-origin",
        cache: "no-store",
        ...options,
        signal: controller.signal,
        headers,
    }); } finally { window.clearTimeout(timeout); }
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || response.redirected || !(response.headers.get("content-type") || "").includes("application/json")) {
        const error = new Error(payload.error || payload.message || ([401, 403].includes(response.status) || response.redirected
            ? "انتهت الجلسة. سجّل الدخول بالحساب نفسه لإكمال المزامنة." : `HTTP ${response.status}`));
        error.status = response.redirected ? 401 : response.status;
        error.code = payload.code;
        throw error;
    }
    return payload;
}

function endpointFor(item) {
    if (!ENDPOINTS[item.entity_name]) throw new Error("نوع العملية غير مدعوم للمزامنة.");
    return ENDPOINTS[item.entity_name];
}

async function operationForServer(item) {
    const deviceId = await getDeviceId();
    return {
        idempotency_key: item.idempotency_key,
        device_id: deviceId,
        entity_type: item.entity_type || DEFAULT_ENTITY_TYPES[item.entity_name] || item.entity_name,
        operation_type: item.operation_type || "create",
        local_uuid: item.local_uuid,
        scope: getOfflineScope(),
        payload: {
            ...(item.payload || {}),
            local_uuid: item.local_uuid,
            queued_at: item.timestamp,
            updated_at: item.payload?.updated_at || item.timestamp || nowIso(),
        },
    };
}

async function applyServerResult(item, result) {
    if (result?.resolution === "server_deleted") {
        await markLocalEntitySynced(item.entity_name, item.local_record_id, result);
        return;
    }
    await markLocalEntitySynced(item.entity_name, item.local_record_id, result || {});
}

async function pushQueueItem(item) {
    const operation = await operationForServer(item);
    const payload = await jsonFetch(endpointFor(item), {
        method: "POST",
        body: JSON.stringify(operation),
    });
    const result = Array.isArray(payload) ? payload[0] : payload;
    if (!result || !["success", "synced", "ignored"].includes(result.status)) {
        const error = new Error(result?.error || "Sync operation failed");
        error.permanent = result?.status === "failed_conflict";
        throw error;
    }
    await applyServerResult(item, result);
    await removeQueueItem(item.id);
    return result;
}

export async function bootstrapNow() {
    if (!navigator.onLine || bootstrapInProgress || !getOfflineScope()) return null;
    bootstrapInProgress = true;
    try {
        const payload = await jsonFetch("/api/sync/bootstrap-browser/");
        await importBootstrap(payload);
        csrfToken = payload.csrf_token || csrfToken;
        lastBootstrapAt = Date.now();
        await setMetadata("last_successful_sync_at", nowIso());
        await cacheAppShell();
        syncStatusEvent({ state: "bootstrapped" });
        return payload;
    } catch (error) {
        syncStatusEvent({ state: "bootstrap_failed", error: String(error.message || error) });
        return null;
    } finally {
        bootstrapInProgress = false;
    }
}

async function processQueueUnlocked() {
    syncInProgress = true;
    syncStatusEvent({ state: "syncing" });
    try {
        // Refresh CSRF and confirm the session/branch before any money or stock
        // operation. An old cached page must not use a new account's cookie.
        const session = await jsonFetch("/api/sync/session/");
        if (session.scope !== getOfflineScope()) throw new Error("تغير الحساب أو المعرض. افتح الصفحة من جديد.");
        csrfToken = session.csrf_token;
        const items = await getDueQueueItems();
        let synced = 0;
        let failed = 0;
        for (const item of items) {
            try {
                await pushQueueItem(item);
                synced += 1;
                syncStatusEvent({ state: "item_synced", item_id: item.id, entity_name: item.entity_name });
            } catch (error) {
                failed += 1;
                if (![401, 403].includes(error.status) && error.code !== "scope_changed") {
                    await markQueueItemFailed(item, error.message || error, { permanent: error.permanent });
                }
                syncStatusEvent({ state: error.permanent ? "conflict" : "item_failed", item_id: item.id, error: String(error.message || error) });
                // Preserve ordering: later operations may depend on this record.
                break;
            }
        }
        if (synced) await setMetadata("last_successful_sync_at", nowIso());
        if (synced && !failed) await bootstrapNow();
        syncStatusEvent({ state: failed ? "pending" : "idle", ...(await getQueueStatus()) });
    } catch (error) {
        syncStatusEvent({ state: [401, 403].includes(error.status) ? "authentication_required" : "sync_failed", error: String(error.message || error) });
    } finally {
        syncInProgress = false;
    }
}

export async function getQueueStatus() {
    if (!getOfflineScope()) return { pending: 0, conflicts: 0 };
    const items = await getAll(STORE_NAMES.syncQueue);
    return { pending: items.length, conflicts: items.filter((item) => item.status === "conflict").length };
}

export async function processQueue() {
    if (!navigator.onLine || syncInProgress || !getOfflineScope()) return;
    const run = () => { if (!syncInProgress) return processQueueUnlocked(); };
    if (navigator.locks?.request) {
        await navigator.locks.request(`sh-sync-${getOfflineScope()}`, { ifAvailable: true }, (lock) => lock ? run() : undefined);
    } else await run(); // Server idempotency still protects browsers without Web Locks.
}

async function startOnlineWork() {
    await processQueue();
    if (Date.now() - lastBootstrapAt > 60000) await bootstrapNow();
}

window.addEventListener("online", startOnlineWork);
window.addEventListener("focus", () => {
    if (navigator.onLine) processQueue();
});

navigator.serviceWorker?.addEventListener("message", (event) => {
    if (event.data?.type === "PROCESS_SYNC") {
        processQueue();
    }
});

if (navigator.onLine && getOfflineScope()) {
    startOnlineWork();
}
window.setInterval(() => {
    if (navigator.onLine && !document.hidden && getOfflineScope()) processQueue();
}, 30000);
navigator.serviceWorker?.addEventListener("controllerchange", () => cacheAppShell());

window.SHSync = {
    bootstrapNow,
    cacheAppShell,
    processQueue,
    getQueueStatus,
};
