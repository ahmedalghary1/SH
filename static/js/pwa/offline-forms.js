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

function formDataToObject(formData) {
    const data = {};
    formData.forEach((value, key) => {
        if (value instanceof File) return;
        if (Object.prototype.hasOwnProperty.call(data, key)) {
            data[key] = Array.isArray(data[key]) ? [...data[key], value] : [data[key], value];
        } else {
            data[key] = value;
        }
    });
    return data;
}

function serializeForm(form, submitter = null) {
    const formData = new FormData(form);
    if (submitter?.name) {
        formData.set(submitter.name, submitter.value || "");
    }
    return formDataToObject(formData);
}

function hasSelectedFiles(form) {
    return Array.from(form.querySelectorAll('input[type="file"]')).some((input) => input.files?.length);
}

function pathFromAction(action) {
    return new URL(action || window.location.href, window.location.origin).pathname;
}

function operationTypeForPath(path) {
    if (path.includes("/delete/") || path.includes("delete")) return "delete";
    if (path.includes("/update/") || path.includes("/edit/") || path.includes("/status/") || path.includes("/confirm/")) return "update";
    return "create";
}

function classifyPath(path) {
    if (path.startsWith("/orders/")) return { entity_name: "sales", entity_type: "order", action_type: "create_invoice" };
    if (path.startsWith("/customers/")) return { entity_name: "customers", entity_type: "customer", action_type: "save_customer" };
    if (path.startsWith("/inventory/")) return { entity_name: "stock", entity_type: "stock", action_type: "stock_movement" };
    if (path.startsWith("/finance/")) return { entity_name: "cash", entity_type: "payment", action_type: "cash_transaction" };
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

function customerPayload(fields, localUuid) {
    return {
        id: localUuid,
        local_uuid: localUuid,
        customer: {
            local_uuid: localUuid,
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

function orderPayload(fields, path, localUuid) {
    const items = parseItemsJson(fields.items_json);
    return {
        id: localUuid,
        local_uuid: localUuid,
        order: {
            local_uuid: localUuid,
            customer_server_id: /^\d+$/.test(String(fields.customer || "")) ? fields.customer : "",
            customer_local_uuid: /^\d+$/.test(String(fields.customer || "")) ? "" : fields.customer || "",
            document_type: fields.document_type || "sale",
            order_type: fields.order_type || "b2c",
            payment_method: fields.payment_method || "cash",
            warehouse: fields.warehouse || "",
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

function genericPayload(fields, path, localUuid, entityType) {
    return {
        id: localUuid,
        local_uuid: localUuid,
        [entityType]: {
            ...fields,
            local_uuid: localUuid,
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
    const quantity = Number(movement.quantity || 0);
    if (!quantity) return;
    if (movement.warehouse && movement.variant) {
        await updateStockQuantity({ variant_id: movement.variant, warehouse_id: movement.warehouse, delta: quantity });
    }
}

async function queueFormSubmission(form, submitter = null) {
    const action = submitter?.formAction || form.action || window.location.href;
    const path = pathFromAction(action);
    const classification = classifyPath(path);
    if (!classification) return false;

    const fields = serializeForm(form, submitter);
    const localUuid = uuid();
    const operationType = operationTypeForPath(path);
    let payload;
    if (classification.entity_name === "customers") {
        payload = customerPayload(fields, localUuid);
    } else if (classification.entity_name === "sales") {
        payload = orderPayload(fields, path, localUuid);
    } else {
        payload = genericPayload(fields, path, localUuid, classification.entity_type);
    }
    payload.source = "pwa-form";
    payload.original_url = path;

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
    const fields = formDataToObject(body);
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
    if (navigator.onLine || event.defaultPrevented) return;
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || !shouldCaptureForm(form)) return;

    event.preventDefault();
    if (hasSelectedFiles(form)) {
        showOfflineNotice("This form contains files and cannot be saved offline.", true);
        return;
    }
    try {
        const queued = await queueFormSubmission(form, event.submitter);
        if (queued) {
            form.dataset.offlineQueued = "true";
            showOfflineNotice("Offline operation saved. It will sync automatically.");
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
