import {
    estimateOrderTotals,
    nowIso,
    priceForVariant,
    queueEntityOperation,
    searchCustomers,
    searchProducts,
    stockForVariant,
    updateStockQuantity,
    uuid,
    variantsForProduct,
} from "./db.js";
import { processQueue } from "./sync-engine.js";

const SERVER_PING_URL = "/api/sync/ping/";
const SERVER_REACHABLE_TTL = 5000;
const SERVER_PING_TIMEOUT = 2500;
const MAX_OFFLINE_FILE_BYTES = 5 * 1024 * 1024;
const SERVER_ENTITY_PREFIX = {
    sales: "order",
    returns: "return",
    customers: "customer",
    products: "product",
    stock: "stock",
    cash: "payment",
    driver_actions: "driver_action",
};

let serverReachableUntil = 0;

function appendValue(target, key, value) {
    if (Object.prototype.hasOwnProperty.call(target, key)) {
        target[key] = Array.isArray(target[key]) ? [...target[key], value] : [target[key], value];
    } else {
        target[key] = value;
    }
}

function fileToPayload(file) {
    return new Promise((resolve, reject) => {
        if (!file || !file.size) {
            resolve(null);
            return;
        }
        if (file.size > MAX_OFFLINE_FILE_BYTES) {
            reject(new Error(`File ${file.name} is larger than 5 MB and cannot be saved offline.`));
            return;
        }
        const reader = new FileReader();
        reader.onload = () => {
            const dataUrl = String(reader.result || "");
            resolve({
                name: file.name,
                type: file.type || "application/octet-stream",
                size: file.size,
                last_modified: file.lastModified || null,
                data: dataUrl.includes(",") ? dataUrl.split(",", 2)[1] : dataUrl,
            });
        };
        reader.onerror = () => reject(reader.error || new Error("Could not read offline file."));
        reader.readAsDataURL(file);
    });
}

async function formDataToObject(formData) {
    const data = {};
    const files = {};
    const fileTasks = [];
    formData.forEach((value, key) => {
        if (value instanceof File) {
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

async function serializeForm(form, submitter = null) {
    const formData = new FormData(form);
    if (submitter?.name) {
        formData.set(submitter.name, submitter.value || "");
    }
    return formDataToObject(formData);
}

function pathFromAction(action) {
    return new URL(action || window.location.href, window.location.origin).pathname;
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

function classifyPath(path) {
    if (path.startsWith("/orders/")) return { entity_name: "sales", entity_type: "order", action_type: "create_invoice" };
    if (path.startsWith("/invoices/") && path.includes("/payments/add/")) return { entity_name: "cash", entity_type: "payment", action_type: "cash_transaction" };
    if (path.includes("/interactions/")) return null;
    if (path.startsWith("/customers/")) return { entity_name: "customers", entity_type: "customer", action_type: "save_customer" };
    if (path.startsWith("/inventory/movements/")) return { entity_name: "stock", entity_type: "stock", action_type: "stock_movement" };
    if (path.startsWith("/finance/transactions/")) return { entity_name: "cash", entity_type: "payment", action_type: "cash_transaction" };
    if (path.startsWith("/sales-reps/")) return { entity_name: "driver_actions", entity_type: "driver_action", action_type: "driver_action" };
    if (path.startsWith("/returns/")) return { entity_name: "returns", entity_type: "return", action_type: "sales_return" };
    if (path.startsWith("/products/")) return { entity_name: "products", entity_type: "product", action_type: "save_product" };
    return null;
}

function showOfflineNotice(message, isError = false) {
    let notice = document.querySelector("[data-offline-notice]");
    if (!notice) {
        notice = document.createElement("div");
        notice.dataset.offlineNotice = "true";
        notice.style.position = "fixed";
        notice.style.insetInlineStart = "18px";
        notice.style.bottom = "18px";
        notice.style.zIndex = "2000";
        notice.style.maxWidth = "360px";
        notice.style.padding = "12px 14px";
        notice.style.borderRadius = "8px";
        notice.style.boxShadow = "0 8px 24px rgba(0,0,0,.16)";
        notice.style.fontWeight = "600";
        document.body.appendChild(notice);
    }
    notice.textContent = message;
    notice.style.background = isError ? "#8b1e2d" : "#123c69";
    notice.style.color = "#fff";
    notice.hidden = false;
    window.clearTimeout(showOfflineNotice.timer);
    showOfflineNotice.timer = window.setTimeout(() => {
        notice.hidden = true;
    }, 5200);
}

function requestBackgroundSync() {
    navigator.serviceWorker?.ready
        ?.then((registration) => registration.sync?.register("sh-sync-queue"))
        .catch(() => {});
}

function parseItemsJson(value) {
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
    const items = parseItemsJson(fields.items_json);
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

async function applyOptimisticStockMutation(classification, payload) {
    if (classification.entity_name === "sales" && payload.items) {
        await Promise.all(payload.items.map((item) => updateStockQuantity({
            variant_id: item.variant_id,
            warehouse_id: item.warehouse_id,
            delta: -Number(item.quantity || 0),
        })));
        return;
    }
    if (classification.entity_name !== "stock") return;
    const movement = payload.stock || {};
    const path = payload.original_url || "";
    const quantity = Number(movement.quantity || 0);
    if (!quantity) return;
    if (path.includes("/transfer/") && movement.from_warehouse && movement.to_warehouse && movement.variant) {
        await updateStockQuantity({ variant_id: movement.variant, warehouse_id: movement.from_warehouse, delta: -quantity });
        await updateStockQuantity({ variant_id: movement.variant, warehouse_id: movement.to_warehouse, delta: quantity });
    } else if (path.includes("/representative-issue/") && movement.from_warehouse && movement.variant) {
        await updateStockQuantity({ variant_id: movement.variant, warehouse_id: movement.from_warehouse, delta: -quantity });
    } else if (path.includes("/representative-return/") && movement.to_warehouse && movement.variant) {
        await updateStockQuantity({ variant_id: movement.variant, warehouse_id: movement.to_warehouse, delta: quantity });
    } else if (movement.warehouse && movement.variant) {
        const delta = path.includes("/out/") ? -quantity : quantity;
        await updateStockQuantity({ variant_id: movement.variant, warehouse_id: movement.warehouse, delta });
    }
}

async function queueFormSubmission(form, submitter = null) {
    const action = submitter?.formAction || form.action || window.location.href;
    const path = pathFromAction(action);
    const classification = classifyPath(path);
    if (!classification) return false;

    const fields = await serializeForm(form, submitter);
    const serverId = serverIdFromPath(path);
    const localUuid = localUuidFor(classification, serverId);
    const operationType = operationTypeForPath(path);
    let payload;
    if (classification.entity_name === "customers") {
        payload = customerPayload(fields, localUuid, serverId);
    } else if (classification.entity_name === "sales") {
        payload = orderPayload(fields, path, localUuid, serverId);
    } else {
        payload = genericPayload(fields, path, localUuid, classification.entity_type, serverId);
    }
    payload.source = "pwa-form";
    payload.original_url = path;
    payload.server_id = serverId || payload.server_id || "";

    await applyOptimisticStockMutation(classification, payload);
    await queueEntityOperation(classification.entity_name, classification.action_type, payload, {
        entity_type: classification.entity_type,
        operation_type: operationType,
    });
    requestBackgroundSync();
    return true;
}

function shouldCaptureForm(form) {
    const method = String(form.method || "get").toLowerCase();
    if (method !== "post") return false;
    const path = pathFromAction(form.action || window.location.href);
    if (path.startsWith("/accounts/") || path.startsWith("/admin/") || path.startsWith("/api/")) return false;
    return Boolean(classifyPath(path));
}

async function handleQuickCustomer(options = {}) {
    const body = options.body instanceof FormData ? options.body : new FormData();
    const fields = await formDataToObject(body);
    const localUuid = uuid();
    const payload = customerPayload(fields, localUuid);
    payload.source = "pwa-ajax";
    await queueEntityOperation("customers", "create_customer", payload, {
        entity_type: "customer",
        operation_type: "create",
    });
    requestBackgroundSync();
    return {
        success: true,
        offline: true,
        message: "Saved offline",
        data: {
            id: localUuid,
            local_uuid: localUuid,
            name: payload.customer.name,
            phone: payload.customer.phone,
            customer_type: payload.customer.customer_type,
        },
    };
}

async function isServerReachable() {
    if (!navigator.onLine) return false;
    if (Date.now() < serverReachableUntil) return true;

    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), SERVER_PING_TIMEOUT);
    try {
        const response = await fetch(`${SERVER_PING_URL}?t=${Date.now()}`, {
            cache: "no-store",
            credentials: "same-origin",
            headers: { Accept: "application/json" },
            signal: controller.signal,
        });
        const reachable = response.ok;
        if (reachable) serverReachableUntil = Date.now() + SERVER_REACHABLE_TTL;
        return reachable;
    } catch (error) {
        return false;
    } finally {
        window.clearTimeout(timeout);
    }
}

function submitNormally(form, submitter = null) {
    const original = {
        action: form.getAttribute("action"),
        method: form.getAttribute("method"),
        enctype: form.getAttribute("enctype"),
        target: form.getAttribute("target"),
    };
    const hidden = [];

    if (submitter) {
        if (submitter.hasAttribute("formaction")) form.action = submitter.formAction;
        if (submitter.hasAttribute("formmethod")) form.method = submitter.formMethod;
        if (submitter.hasAttribute("formenctype")) form.enctype = submitter.formEnctype;
        if (submitter.hasAttribute("formtarget")) form.target = submitter.formTarget;
        if (submitter.name) {
            const input = document.createElement("input");
            input.type = "hidden";
            input.name = submitter.name;
            input.value = submitter.value || "";
            form.appendChild(input);
            hidden.push(input);
        }
    }

    HTMLFormElement.prototype.submit.call(form);

    hidden.forEach((input) => input.remove());
    Object.entries(original).forEach(([key, value]) => {
        if (value === null) form.removeAttribute(key);
        else form.setAttribute(key, value);
    });
}

export async function handleJsonRequest(url, options = {}) {
    const parsed = new URL(url, window.location.origin);
    const path = parsed.pathname;

    if (path === "/orders/ajax/search-products/") {
        return { success: true, message: "Loaded offline", data: await searchProducts(parsed.searchParams.get("q") || "") };
    }
    const productVariantsMatch = path.match(/^\/orders\/ajax\/products\/([^/]+)\/variants\/$/);
    if (productVariantsMatch) {
        return { success: true, message: "Loaded offline", data: await variantsForProduct(productVariantsMatch[1]) };
    }
    const variantStockMatch = path.match(/^\/orders\/ajax\/variants\/([^/]+)\/stock\/$/);
    if (variantStockMatch) {
        return {
            success: true,
            message: "Loaded offline",
            data: { warehouses: await stockForVariant(variantStockMatch[1]) },
        };
    }
    if (path === "/inventory/ajax/variant-warehouses/") {
        return {
            success: true,
            message: "Loaded offline",
            data: { warehouses: await stockForVariant(parsed.searchParams.get("variant_id") || "") },
        };
    }
    const variantPriceMatch = path.match(/^\/orders\/ajax\/variants\/([^/]+)\/price\/$/);
    if (variantPriceMatch) {
        return {
            success: true,
            message: "Loaded offline",
            data: { price: await priceForVariant(variantPriceMatch[1], parsed.searchParams.get("order_type") || "b2c") },
        };
    }
    if (path === "/orders/ajax/search-customers/" || path === "/customers/ajax/search/") {
        return { success: true, message: "Loaded offline", data: await searchCustomers(parsed.searchParams.get("q") || "") };
    }
    if (path === "/customers/ajax/quick-create/" && String(options.method || "GET").toUpperCase() === "POST") {
        return handleQuickCustomer(options);
    }
    if (path === "/orders/ajax/calculate/" && options.body) {
        const body = typeof options.body === "string" ? JSON.parse(options.body || "{}") : {};
        return { success: true, message: "Calculated offline", data: await estimateOrderTotals(body) };
    }
    throw new Error("No offline handler for this request");
}

document.addEventListener("submit", async (event) => {
    if (event.defaultPrevented) return;
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || !shouldCaptureForm(form)) return;

    event.preventDefault();
    const submitter = event.submitter;

    if (await isServerReachable()) {
        submitNormally(form, submitter);
        return;
    }

    try {
        const queued = await queueFormSubmission(form, submitter);
        if (queued) {
            form.dataset.offlineQueued = "true";
            showOfflineNotice("Saved offline. It will sync automatically when the server is available.");
        }
    } catch (error) {
        showOfflineNotice(`Offline save failed: ${error.message || error}`, true);
    }
});

window.addEventListener("online", () => {
    document.body.classList.remove("is-offline");
    processQueue();
});

window.addEventListener("offline", () => {
    document.body.classList.add("is-offline");
    showOfflineNotice("Offline mode is active. New work will be queued locally.");
});

if (!navigator.onLine) {
    document.body.classList.add("is-offline");
}

window.SHOffline = {
    handleJsonRequest,
    queueFormSubmission,
};
