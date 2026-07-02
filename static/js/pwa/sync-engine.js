import {
    getDeviceId,
    getDueQueueItems,
    importBootstrap,
    markLocalEntitySynced,
    markQueueItemFailed,
    nowIso,
    removeQueueItem,
    setMetadata,
} from "./db.js";

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
    if (!("serviceWorker" in navigator)) return;
    const urls = uniqueUrls([
        ...APP_SHELL_URLS,
        window.location.pathname,
        ...extraUrls,
    ]);
    if (!urls.length) return;

    try {
        const registration = await navigator.serviceWorker.ready;
        const worker = navigator.serviceWorker.controller || registration.active || registration.waiting || registration.installing;
        worker?.postMessage({ type: "CACHE_URLS", urls });
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
    const csrf = getCookie("csrftoken");
    if (csrf) headers["X-CSRFToken"] = csrf;
    const response = await fetch(url, {
        credentials: "same-origin",
        ...options,
        headers,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(payload.error || payload.message || `HTTP ${response.status}`);
    }
    return payload;
}

function endpointFor(item) {
    return ENDPOINTS[item.entity_name] || ENDPOINTS.sales;
}

async function operationForServer(item) {
    const deviceId = await getDeviceId();
    return {
        idempotency_key: item.idempotency_key,
        device_id: deviceId,
        entity_type: item.entity_type || DEFAULT_ENTITY_TYPES[item.entity_name] || item.entity_name,
        operation_type: item.operation_type || "create",
        local_uuid: item.local_uuid,
        payload: {
            ...(item.payload || {}),
            local_uuid: item.local_uuid,
            queued_at: item.timestamp,
            updated_at: item.payload?.updated_at || item.updated_at || item.timestamp || nowIso(),
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
        throw new Error(result?.error || "Sync operation failed");
    }
    await applyServerResult(item, result);
    await removeQueueItem(item.id);
    return result;
}

export async function bootstrapNow() {
    if (!navigator.onLine || bootstrapInProgress) return null;
    bootstrapInProgress = true;
    try {
        const payload = await jsonFetch("/api/sync/bootstrap-browser/");
        await importBootstrap(payload);
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

export async function processQueue() {
    if (!navigator.onLine || syncInProgress) return;
    syncInProgress = true;
    syncStatusEvent({ state: "syncing" });
    try {
        const items = await getDueQueueItems();
        for (const item of items) {
            try {
                await pushQueueItem(item);
                syncStatusEvent({ state: "item_synced", item_id: item.id, entity_name: item.entity_name });
            } catch (error) {
                await markQueueItemFailed(item, error.message || error);
                syncStatusEvent({ state: "item_failed", item_id: item.id, error: String(error.message || error) });
            }
        }
        await setMetadata("last_successful_sync_at", nowIso());
        if (items.length) await bootstrapNow();
        syncStatusEvent({ state: "idle" });
    } finally {
        syncInProgress = false;
    }
}

async function startOnlineWork() {
    await cacheAppShell();
    await bootstrapNow();
    await processQueue();
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

if (navigator.onLine) {
    startOnlineWork();
}

window.SHSync = {
    bootstrapNow,
    cacheAppShell,
    processQueue,
};
