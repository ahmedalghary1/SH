import { getAll, STORE_NAMES } from "./db.js";

const PENDING_STATUSES = new Set(["pending", "failed"]);
let renderScheduled = false;

function text(value, fallback = "-") {
    const normalized = String(value ?? "").trim();
    return normalized || fallback;
}

function money(value) {
    const number = Number(value || 0);
    return Number.isFinite(number) ? number.toFixed(2) : text(value, "0.00");
}

function formatDate(value) {
    const date = value ? new Date(value) : new Date();
    if (Number.isNaN(date.getTime())) return text(value);
    return date.toLocaleString("ar-EG", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
    });
}

function firstValue(value, fallback = "") {
    if (Array.isArray(value)) {
        const found = value.find((item) => item !== undefined && item !== null && item !== "");
        return found ?? fallback;
    }
    return value ?? fallback;
}

function isPendingItem(item) {
    return PENDING_STATUSES.has(item.status) && item.operation_type !== "delete";
}

function itemDate(item) {
    return Date.parse(item.timestamp || item.updated_at || item.created_at || "") || 0;
}

async function getPendingQueue() {
    const queue = await getAll(STORE_NAMES.syncQueue);
    return queue
        .filter(isPendingItem)
        .sort((a, b) => itemDate(b) - itemDate(a));
}

async function customerLookup() {
    const customers = await getAll(STORE_NAMES.customers);
    const lookup = new Map();
    customers.forEach((record) => {
        const data = record.customer || record;
        const label = text(data.name || record.name);
        [record.id, record.local_uuid, record.server_id, data.local_uuid, data.server_id]
            .filter(Boolean)
            .forEach((key) => {
                lookup.set(String(key), label);
                lookup.set(`server-customer-${key}`, label);
            });
    });
    return lookup;
}

function td(content, className = "") {
    const cell = document.createElement("td");
    if (content instanceof Node) {
        cell.appendChild(content);
    } else {
        cell.textContent = text(content);
    }
    if (className) cell.className = className;
    return cell;
}

function badge(label = "محلي") {
    const element = document.createElement("span");
    element.className = "badge warning";
    element.textContent = label;
    return element;
}

function localRef(item, prefix = "محلي") {
    return `${prefix}-${String(item.local_uuid || item.id || "").slice(0, 8)}`;
}

function totalForItems(items = []) {
    return items.reduce((sum, item) => {
        const quantity = Number(item.quantity || 0);
        const price = Number(item.unit_price || item.price || item.unit_cost || 0);
        const discount = Number(item.discount_amount || item.discount || 0);
        return sum + Math.max(0, (quantity * price) - discount);
    }, 0);
}

function orderPayload(item) {
    const payload = item.payload || {};
    return {
        payload,
        order: payload.order || {},
        items: Array.isArray(payload.items) ? payload.items : [],
        form: payload.form || {},
    };
}

function customerNameForOrder(item, lookup) {
    const { order, form } = orderPayload(item);
    const key = order.customer_local_uuid || order.customer_server_id || form.customer || order.customer;
    return lookup.get(String(key || "")) || order.customer_name || form.customer_name || "عميل محلي";
}

function paymentLabel(value) {
    const labels = {
        cash: "نقدي",
        credit: "آجل",
        card: "بطاقة",
        wallet: "محفظة",
        bank_transfer: "تحويل بنكي",
    };
    return labels[value] || text(value);
}

function statusLabel(item) {
    return item.status === "failed" ? "تعذر المزامنة" : "قيد المزامنة";
}

function removeEmptyRows(tbody) {
    tbody.querySelectorAll("tr").forEach((row) => {
        if (row.dataset.offlineRow) return;
        const cells = row.querySelectorAll("td");
        if (cells.length === 1 && cells[0].hasAttribute("colspan")) row.remove();
    });
}

function clearOfflineRows() {
    document.querySelectorAll("[data-offline-row], [data-offline-card]").forEach((element) => element.remove());
}

function insertRows(rows, tbody = document.querySelector("table tbody")) {
    if (!tbody || !rows.length) return;
    removeEmptyRows(tbody);
    const anchor = tbody.querySelector("tr:not([data-offline-row])");
    rows.forEach((row) => tbody.insertBefore(row, anchor));
}

function makeRow(item, cells) {
    const row = document.createElement("tr");
    row.dataset.offlineRow = item.id;
    row.classList.add("offline-row");
    cells.forEach((cell) => row.appendChild(cell));
    return row;
}

function renderOrders(queue, lookup, mode = "orders") {
    const rows = queue
        .filter((item) => item.entity_name === "sales")
        .filter((item) => {
            const { order } = orderPayload(item);
            if (mode === "quotes") return order.document_type === "quote";
            if (mode === "invoices") return order.document_type !== "quote";
            return order.document_type !== "quote";
        })
        .map((item) => {
            const { order, items } = orderPayload(item);
            const total = totalForItems(items);
            const paid = Number(order.paid_amount || 0);
            if (mode === "invoices") {
                return makeRow(item, [
                    td(Object.assign(document.createElement("input"), { type: "checkbox", disabled: true })),
                    td(localRef(item, "فاتورة")),
                    td(localRef(item, "طلب")),
                    td(customerNameForOrder(item, lookup)),
                    td("-"),
                    td("محلي"),
                    td(money(total)),
                    td(money(paid)),
                    td(money(Math.max(0, total - paid))),
                    td(badge(statusLabel(item))),
                    td(paymentLabel(order.payment_method)),
                    td(formatDate(item.timestamp)),
                    td(badge("محلي"), "actions"),
                ]);
            }
            return makeRow(item, [
                td(localRef(item, "فاتورة")),
                td(order.document_type === "quote" ? "عرض سعر" : "فاتورة"),
                td(customerNameForOrder(item, lookup)),
                td(paymentLabel(order.payment_method)),
                td(money(total)),
                td(money(order.discount_amount || order.discount || 0)),
                td(formatDate(item.timestamp)),
                td("محلي"),
                td(badge(statusLabel(item))),
            ]);
        });
    insertRows(rows);
}

function customerData(item) {
    const payload = item.payload || {};
    return payload.customer || payload.form || payload;
}

function renderCustomers(queue) {
    const tbody = document.querySelector("table tbody");
    const colCount = document.querySelectorAll("table thead th").length || 8;
    const rows = queue
        .filter((item) => item.entity_name === "customers")
        .map((item) => {
            const data = customerData(item);
            const common = [
                td(data.name || data.customer_name || "عميل محلي"),
                td(data.phone || "-"),
                td(data.customer_type === "wholesale" ? "جملة" : "قطاعي"),
            ];
            if (colCount >= 9) common.push(td(data.sales_representative || "-"));
            common.push(
                td("0"),
                td(data.opening_balance || "0"),
                td(formatDate(item.timestamp)),
                td(badge(statusLabel(item))),
                td(badge("محلي")),
            );
            return makeRow(item, common.slice(0, colCount));
        });
    insertRows(rows, tbody);
}

function productData(item) {
    const payload = item.payload || {};
    return payload.product || payload.form || payload;
}

function renderProducts(queue) {
    const path = window.location.pathname;
    if (path.startsWith("/products/categories/") || path.startsWith("/products/colors/") || path.startsWith("/products/sizes/")) {
        renderProductCatalog(queue, path);
        return;
    }

    const grid = document.querySelector(".products-grid");
    if (!grid) return;
    document.querySelectorAll(".products-grid .empty-state").forEach((element) => element.remove());
    queue
        .filter((item) => item.entity_name === "products")
        .forEach((item) => {
            const data = productData(item);
            const card = document.createElement("div");
            card.className = "product-card offline-card";
            card.dataset.offlineCard = item.id;
            card.innerHTML = `
                <div class="product-image"><span class="no-image">-</span></div>
                <div class="product-info">
                    <h3></h3>
                    <div class="product-meta">
                        <span class="sku"></span>
                        <span class="category"></span>
                    </div>
                    <div class="product-stats">
                        <span class="quantity"></span>
                        <span class="quantity"></span>
                        <span class="status active">محلي</span>
                    </div>
                </div>
                <div class="product-actions"><span class="badge warning">قيد المزامنة</span></div>
            `;
            card.querySelector("h3").textContent = text(data.name || data.new_product_name, "منتج محلي");
            card.querySelector(".sku").textContent = text(data.sku || data.new_product_sku, localRef(item, "SKU"));
            card.querySelector(".category").textContent = text(data.new_category_name || data.category, "-");
            const quantities = card.querySelectorAll(".quantity");
            quantities[0].textContent = `${text(data.quantity, "0")} قطعة`;
            quantities[1].textContent = `${text(data.pieces_per_dozen, "12")} قطعة/دستة`;
            grid.prepend(card);
        });
}

function renderProductCatalog(queue, path) {
    const rows = queue
        .filter((item) => item.entity_name === "products")
        .filter((item) => {
            const original = item.payload?.original_url || "";
            if (path.startsWith("/products/categories/")) {
                return original.includes("/products/categories/") || original.includes("/quick-create-category/");
            }
            if (path.startsWith("/products/colors/")) {
                return original.includes("/products/colors/") || original.includes("/quick-create-color/");
            }
            return original.includes("/products/sizes/") || original.includes("/quick-create-size/");
        })
        .map((item) => {
            const data = productData(item);
            if (path.startsWith("/products/categories/")) {
                return makeRow(item, [
                    td(data.name || "تصنيف محلي"),
                    td(data.parent || "-"),
                    td(badge(statusLabel(item))),
                    td(badge("محلي"), "actions"),
                ]);
            }
            if (path.startsWith("/products/colors/")) {
                return makeRow(item, [
                    td(data.name || "لون محلي"),
                    td(data.hex_code || "-"),
                    td(data.hex_code || "-"),
                    td(badge("محلي"), "actions"),
                ]);
            }
            return makeRow(item, [
                td(data.name || "مقاس محلي"),
                td(data.sort_order || "0"),
                td(badge(statusLabel(item)), "actions"),
            ]);
        });
    insertRows(rows);
}

function paymentData(item) {
    const payload = item.payload || {};
    return payload.payment || payload.form || payload;
}

function renderFinance(queue) {
    const path = window.location.pathname;
    if (path.startsWith("/finance/accounts/")) {
        const rows = queue
            .filter((item) => item.entity_name === "cash" && (item.payload?.original_url || "").startsWith("/finance/accounts/"))
            .map((item) => {
                const data = paymentData(item);
                return makeRow(item, [
                    td(data.name || "حساب محلي"),
                    td(data.account_type || "-"),
                    td(data.assigned_user || "-"),
                    td(money(data.balance)),
                    td(badge(statusLabel(item))),
                    td(badge("محلي"), "actions"),
                ]);
            });
        insertRows(rows);
        return;
    }

    if (path.startsWith("/finance/transactions/collection/")) {
        const rows = queue
            .filter((item) => item.entity_name === "cash")
            .filter((item) => (item.payload?.original_url || "").startsWith("/finance/transactions/collection/"))
            .map((item) => {
                const data = paymentData(item);
                const recordedAt = data.transaction_date || item.timestamp;
                return makeRow(item, [
                    td(formatDate(recordedAt)),
                    td(recordedAt ? new Date(recordedAt).toLocaleTimeString("ar-EG", { hour: "2-digit", minute: "2-digit" }) : "-"),
                    td(data.customer || "عميل محلي"),
                    td(money(data.amount)),
                    td(data.cash_account || "-"),
                    td(data.order || "-"),
                    td(data.notes || "-"),
                    td(badge(statusLabel(item))),
                    td(badge("محلي"), "actions"),
                ]);
            });
        insertRows(rows);
        return;
    }

    const selectedType = new URLSearchParams(window.location.search).get("type") || "";
    function inferredTransactionType(item, data) {
        if (data.transaction_type) return data.transaction_type;
        const originalUrl = item.payload?.original_url || "";
        if (originalUrl.includes("/collection/")) return "customer_payment";
        if (originalUrl.includes("/expense/")) return "expense";
        if (originalUrl.includes("/supplier-payment/")) return "supplier_payment";
        if (originalUrl.includes("/transfer/")) return "transfer";
        return "";
    }

    const rows = queue
        .filter((item) => item.entity_name === "cash" && !(item.payload?.original_url || "").startsWith("/finance/accounts/"))
        .filter((item) => {
            if (!selectedType) return true;
            return inferredTransactionType(item, paymentData(item)) === selectedType;
        })
        .map((item) => {
            const data = paymentData(item);
            const transactionType = inferredTransactionType(item, data);
            return makeRow(item, [
                td(transactionType || item.action_type || "حركة مالية"),
                td(transactionType === "expense" || transactionType === "supplier_payment" ? "خارج" : "داخل"),
                td(data.cash_account || data.from_account || "-"),
                td(money(data.amount)),
                td(data.order || "-"),
                td(data.customer || "-"),
                td(data.supplier || data.related_supplier_name || "-"),
                td(data.sales_rep || "-"),
                td(data.transaction_date || formatDate(item.timestamp)),
                td(badge(statusLabel(item))),
                td(badge("محلي"), "actions"),
            ]);
        });
    insertRows(rows);
}

function stockData(item) {
    const payload = item.payload || {};
    return payload.stock || payload.form || payload;
}

function renderInventory(queue) {
    const path = window.location.pathname;
    if (path.startsWith("/inventory/warehouses/")) {
        const rows = queue
            .filter((item) => item.entity_name === "stock" && (item.payload?.original_url || "").startsWith("/inventory/warehouses/"))
            .map((item) => {
                const data = stockData(item);
                return makeRow(item, [
                    td(data.name || data.new_warehouse_name || "مخزن محلي"),
                    td(data.warehouse_type || "main"),
                    td(data.assigned_user || "-"),
                    td(data.address || "-"),
                    td(badge(statusLabel(item))),
                    td(badge("محلي")),
                ]);
            });
        insertRows(rows);
        return;
    }

    const rows = queue
        .filter((item) => item.entity_name === "stock" && !(item.payload?.original_url || "").startsWith("/inventory/warehouses/"))
        .map((item) => {
            const data = stockData(item);
            return makeRow(item, [
                td(item.action_type || "حركة مخزنية"),
                td(data.product_name || data.variant || data.product_variant || "-"),
                td("-"),
                td("-"),
                td(data.from_warehouse || data.warehouse || "-"),
                td(data.to_warehouse || "-"),
                td(data.quantity || data.new_quantity || "0"),
                td("محلي"),
                td(formatDate(item.timestamp)),
                td(data.note || data.notes || statusLabel(item)),
            ]);
        });
    insertRows(rows);
}

function purchaseData(item) {
    const payload = item.payload || {};
    return payload.purchase || payload.form || payload;
}

function renderPurchases(queue) {
    const rows = queue
        .filter((item) => item.entity_name === "purchases")
        .filter((item) => {
            const originalUrl = item.payload?.original_url || "";
            return originalUrl.startsWith("/purchases/orders/")
                && !["/return/", "/pay/", "/receive/", "/cancel/", "/delete/"].some((part) => originalUrl.includes(part));
        })
        .map((item) => {
            const data = purchaseData(item);
            const items = (() => {
                try {
                    const parsed = JSON.parse(data.items_json || "[]");
                    return Array.isArray(parsed) ? parsed : [];
                } catch (error) {
                    return [];
                }
            })();
            const total = items.length
                ? items.reduce((sum, row) => sum + (Number(row.quantity || 0) * Number(row.unit_cost || 0)), 0)
                : Number(data.quantity || 0) * Number(data.unit_cost || 0);
            return makeRow(item, [
                td(localRef(item, "شراء")),
                td(data.new_supplier_name || data.supplier_name || data.supplier || "مورد محلي"),
                td(data.invoice_datetime ? formatDate(data.invoice_datetime) : formatDate(item.timestamp)),
                td(badge(statusLabel(item))),
                td(money(total)),
                td(money(data.paid_amount || 0)),
                td(money(Math.max(0, total - Number(data.paid_amount || 0)))),
                td(badge("محلي")),
            ]);
        });
    insertRows(rows);
}

function renderSuppliers(queue) {
    const colCount = document.querySelectorAll("table thead th").length || 6;
    const rows = queue
        .filter((item) => item.entity_name === "purchases")
        .filter((item) => {
            const original = item.payload?.original_url || "";
            return (original.startsWith("/purchases/suppliers/") && !original.includes("/raw-purchase/"))
                || original.includes("/quick-create-supplier/");
        })
        .map((item) => {
            const data = purchaseData(item);
            if (colCount >= 8) {
                return makeRow(item, [
                    td(data.name || data.new_supplier_name || "مورد محلي"),
                    td(data.phone || data.new_supplier_phone || "-"),
                    td("0"),
                    td("0"),
                    td(data.opening_balance || "0"),
                    td(formatDate(item.timestamp)),
                    td(badge(statusLabel(item))),
                    td(badge("محلي")),
                ]);
            }
            return makeRow(item, [
                td(data.name || data.new_supplier_name || "مورد محلي"),
                td(data.company_name || "-"),
                td(data.phone || data.new_supplier_phone || "-"),
                td(data.email || "-"),
                td(data.address || "-"),
                td(badge(statusLabel(item)), "actions"),
            ]);
        });
    insertRows(rows);
}

function renderReturns(queue) {
    const rows = queue
        .filter((item) => item.entity_name === "returns")
        .map((item) => {
            const payload = item.payload || {};
            const data = payload.return || payload.form || {};
            return makeRow(item, [
                td(localRef(item, "مرتجع")),
                td(data.order || data.invoice_number || "-"),
                td(data.customer || "عميل محلي"),
                td(data.return_type || "مرتجع"),
                td(badge(statusLabel(item))),
                td(money(data.refund_amount)),
                td(formatDate(item.timestamp)),
                td(badge("محلي")),
            ]);
        });
    insertRows(rows);
}

function renderDriverActions(queue) {
    const rows = queue
        .filter((item) => item.entity_name === "driver_actions")
        .map((item) => {
            const payload = item.payload || {};
            const data = payload.driver_action || payload.form || {};
            return makeRow(item, [
                td(item.action_type || "حركة مندوب"),
                td(data.sales_rep || data.representative || "-"),
                td(data.product_variant || data.assignment || "-"),
                td(data.quantity || data.amount || "0"),
                td(badge(statusLabel(item))),
            ]);
        });
    insertRows(rows);
}

async function renderOfflineRecords() {
    clearOfflineRows();
    const queue = await getPendingQueue();
    if (!queue.length) return;
    const path = window.location.pathname;
    const lookup = await customerLookup();

    if (path.startsWith("/invoices/")) renderOrders(queue, lookup, "invoices");
    else if (path.startsWith("/orders/quotes/")) renderOrders(queue, lookup, "quotes");
    else if (path.startsWith("/orders/")) renderOrders(queue, lookup, "orders");
    else if (path.startsWith("/customers/")) renderCustomers(queue);
    else if (path.startsWith("/products/")) renderProducts(queue);
    else if (path.startsWith("/finance/")) renderFinance(queue);
    else if (path.startsWith("/inventory/")) renderInventory(queue);
    else if (path.startsWith("/purchases/orders/")) renderPurchases(queue);
    else if (path.startsWith("/purchases/suppliers/")) renderSuppliers(queue);
    else if (path.startsWith("/returns/")) renderReturns(queue);
    else if (path.startsWith("/sales-reps/")) renderDriverActions(queue);
}

function scheduleRender() {
    if (renderScheduled) return;
    renderScheduled = true;
    window.setTimeout(() => {
        renderScheduled = false;
        renderOfflineRecords().catch((error) => {
            console.warn("Could not render offline records", error);
        });
    }, 50);
}

window.addEventListener("DOMContentLoaded", scheduleRender);
window.addEventListener("pageshow", scheduleRender);
window.addEventListener("focus", scheduleRender);
window.addEventListener("sh-sync-status", scheduleRender);

window.SHOfflineLists = {
    render: renderOfflineRecords,
};
