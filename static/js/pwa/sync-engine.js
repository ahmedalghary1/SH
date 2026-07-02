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
};

const DEFAULT_ENTITY_TYPES = {
    sales: "order",
    returns: "return",
    customers: "customer",
    products: "product",
    stock: "stock",
    cash: "payment",
    driver_actions: "driver_action",
};

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
    processQueue,
};
