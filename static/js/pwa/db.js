const DB_NAME = "sh-offline-db";
const DB_VERSION = 2;

export const STORE_NAMES = {
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

let dbPromise = null;

export function uuid() {
    if (crypto?.randomUUID) return crypto.randomUUID();
    return "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (char) => {
        const value = Number(char) ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (Number(char) / 4)));
        return value.toString(16);
    });
}

export function nowIso() {
    return new Date().toISOString();
}

function createStore(db, name, options = { keyPath: "id" }) {
    if (!db.objectStoreNames.contains(name)) {
        return db.createObjectStore(name, options);
    }
    return null;
}

function addEntityIndexes(store) {
    if (!store) return;
    store.createIndex("sync_status", "sync_status", { unique: false });
    store.createIndex("updated_at", "updated_at", { unique: false });
    store.createIndex("server_id", "server_id", { unique: false });
}

export function openOfflineDB() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise((resolve, reject) => {
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
            if (queue) {
                queue.createIndex("status", "status", { unique: false });
                queue.createIndex("entity_name", "entity_name", { unique: false });
                queue.createIndex("timestamp", "timestamp", { unique: false });
                queue.createIndex("next_attempt_at", "next_attempt_at", { unique: false });
            }
            createStore(db, STORE_NAMES.metadata, { keyPath: "key" });
        };
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
    });
    return dbPromise;
}

async function withStore(storeName, mode, callback) {
    const db = await openOfflineDB();
    return new Promise((resolve, reject) => {
        const tx = db.transaction(storeName, mode);
        const store = tx.objectStore(storeName);
        let result;
        tx.oncomplete = () => resolve(result);
        tx.onerror = () => reject(tx.error);
        tx.onabort = () => reject(tx.error);
        result = callback(store, tx);
    });
}

async function requestResult(request) {
    return new Promise((resolve, reject) => {
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
    });
}

export function withRecordMeta(record, operationType = "create", syncStatus = "pending") {
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

export async function putRecord(storeName, record) {
    const prepared = withRecordMeta(record, record.operation_type, record.sync_status);
    await withStore(storeName, "readwrite", (store) => {
        store.put(prepared);
    });
    return prepared;
}

export async function getRecord(storeName, id) {
    return withStore(storeName, "readonly", (store) => requestResult(store.get(id)));
}

export async function deleteRecord(storeName, id) {
    return withStore(storeName, "readwrite", (store) => {
        store.delete(id);
    });
}

export async function getAll(storeName) {
    return withStore(storeName, "readonly", (store) => requestResult(store.getAll()));
}

export async function setMetadata(key, value) {
    await withStore(STORE_NAMES.metadata, "readwrite", (store) => {
        store.put({ key, value, updated_at: nowIso() });
    });
    return value;
}

export async function getMetadata(key) {
    const row = await withStore(STORE_NAMES.metadata, "readonly", (store) => requestResult(store.get(key)));
    return row?.value;
}

export async function getDeviceId() {
    let deviceId = await getMetadata("device_id");
    if (!deviceId) {
        deviceId = uuid();
        await setMetadata("device_id", deviceId);
    }
    return deviceId;
}

export function storeForEntity(entityName) {
    return ENTITY_STORE[entityName] || STORE_NAMES.syncQueue;
}

export async function saveLocalEntity(entityName, payload, operationType = "create") {
    const storeName = storeForEntity(entityName);
    if (storeName === STORE_NAMES.syncQueue) return null;
    const recordUuid = payload.local_uuid || payload.id || uuid();
    const record = withRecordMeta(
        {
            ...payload,
            id: payload.id || recordUuid,
            local_uuid: payload.local_uuid || recordUuid,
        },
        operationType,
        "pending",
    );
    await putRecord(storeName, record);
    return record;
}

export async function enqueueOperation({
    action_type,
    entity_name,
    entity_type,
    payload,
    operation_type = "create",
    local_uuid,
    local_record_id,
}) {
    const timestamp = nowIso();
    const queueItem = {
        id: uuid(),
        action_type,
        entity_name,
        entity_type,
        operation_type,
        payload,
        local_uuid: local_uuid || payload?.local_uuid || local_record_id || uuid(),
        local_record_id: local_record_id || payload?.id || null,
        timestamp,
        status: "pending",
        attempts: 0,
        next_attempt_at: timestamp,
        idempotency_key: uuid(),
        created_at: timestamp,
        updated_at: timestamp,
        sync_status: "pending",
    };
    await putRecord(STORE_NAMES.syncQueue, queueItem);
    return queueItem;
}

export async function queueEntityOperation(entityName, actionType, payload, options = {}) {
    const localRecord = await saveLocalEntity(entityName, payload, options.operation_type || "create");
    return enqueueOperation({
        action_type: actionType,
        entity_name: entityName,
        entity_type: options.entity_type,
        operation_type: options.operation_type || "create",
        payload: {
            ...payload,
            local_uuid: localRecord?.local_uuid || payload.local_uuid,
            updated_at: localRecord?.updated_at || payload.updated_at || nowIso(),
        },
        local_uuid: localRecord?.local_uuid || payload.local_uuid,
        local_record_id: localRecord?.id || payload.id,
    });
}

export async function getDueQueueItems() {
    const items = await getAll(STORE_NAMES.syncQueue);
    const now = Date.now();
    return items
        .filter((item) => ["pending", "failed"].includes(item.status))
        .filter((item) => !item.next_attempt_at || Date.parse(item.next_attempt_at) <= now)
        .sort((a, b) => Date.parse(a.timestamp || a.created_at) - Date.parse(b.timestamp || b.created_at));
}

export async function removeQueueItem(id) {
    await deleteRecord(STORE_NAMES.syncQueue, id);
}

export async function markQueueItemFailed(item, error) {
    const attempts = Number(item.attempts || 0) + 1;
    const delay = Math.min(5 * 60 * 1000, 1000 * (2 ** attempts));
    const failed = {
        ...item,
        attempts,
        status: "failed",
        sync_status: "failed",
        error: String(error || "Sync failed"),
        next_attempt_at: new Date(Date.now() + delay).toISOString(),
        updated_at: nowIso(),
    };
    await putRecord(STORE_NAMES.syncQueue, failed);
    return failed;
}

export async function markLocalEntitySynced(entityName, localId, serverResult = {}) {
    const storeName = storeForEntity(entityName);
    if (!localId || storeName === STORE_NAMES.syncQueue) return;
    const existing = await getRecord(storeName, localId);
    if (!existing) return;
    await putRecord(storeName, {
        ...existing,
        server_id: serverResult.server_id || existing.server_id,
        server_model: serverResult.server_model || existing.server_model,
        sync_status: "synced",
        operation_type: existing.operation_type || "create",
        sync_resolution: serverResult.resolution || "synced",
        updated_at: nowIso(),
    });
}

function normalizeText(value) {
    return String(value || "")
        .trim()
        .toLowerCase()
        .replace(/[\u064b-\u065f\u0670\u0640]/g, "")
        .replace(/[أإآٱ]/g, "ا")
        .replace(/[ىي]/g, "ي")
        .replace(/ؤ/g, "و")
        .replace(/ة/g, "ه")
        .replace(/ء/g, "")
        .replace(/\s+/g, " ");
}

function serverKey(prefix, id) {
    return String(id || "").startsWith(`${prefix}-`) ? String(id) : `${prefix}-${id}`;
}

export async function importBootstrap(payload) {
    const importedAt = nowIso();
    await setMetadata("last_bootstrap_at", importedAt);
    if (payload.user) await setMetadata("user", payload.user);
    if (payload.company) await setMetadata("company", payload.company);
    if (payload.cash) await setMetadata("cash", payload.cash);

    await Promise.all((payload.products || []).map((product) => putRecord(STORE_NAMES.products, {
        ...product,
        id: serverKey("server-product", product.id),
        server_id: product.id,
        sync_status: "synced",
        operation_type: "update",
        created_at: product.created_at || product.updated_at || importedAt,
        updated_at: product.updated_at || importedAt,
    })));
    await Promise.all((payload.variants || []).map((variant) => putRecord(STORE_NAMES.productVariants, {
        ...variant,
        id: serverKey("server-variant", variant.id),
        server_id: variant.id,
        sync_status: "synced",
        operation_type: "update",
        created_at: variant.created_at || variant.updated_at || importedAt,
        updated_at: variant.updated_at || importedAt,
    })));
    await Promise.all((payload.customers || []).map((customer) => putRecord(STORE_NAMES.customers, {
        ...customer,
        id: customer.local_uuid || serverKey("server-customer", customer.id),
        local_uuid: customer.local_uuid || serverKey("server-customer", customer.id),
        server_id: customer.id,
        sync_status: "synced",
        operation_type: "update",
        created_at: customer.created_at || customer.updated_at || importedAt,
        updated_at: customer.updated_at || importedAt,
    })));
    await Promise.all((payload.orders || []).map((order) => putRecord(STORE_NAMES.sales, {
        ...order,
        id: order.local_uuid || serverKey("server-order", order.id),
        local_uuid: order.local_uuid || serverKey("server-order", order.id),
        server_id: order.id,
        sync_status: "synced",
        operation_type: "update",
        created_at: order.created_at || importedAt,
        updated_at: order.updated_at || importedAt,
    })));
    await Promise.all((payload.stock || []).map((stock) => putRecord(STORE_NAMES.stock, {
        ...stock,
        id: `${stock.warehouse_id}:${stock.variant_id}`,
        sync_status: "synced",
        operation_type: "update",
        created_at: stock.updated_at || importedAt,
        updated_at: stock.updated_at || importedAt,
    })));
    await Promise.all((payload.warehouses || []).map((warehouse) => putRecord(STORE_NAMES.warehouses, {
        ...warehouse,
        id: `server-warehouse-${warehouse.id}`,
        server_id: warehouse.id,
        sync_status: "synced",
        operation_type: "update",
        created_at: warehouse.updated_at || importedAt,
        updated_at: warehouse.updated_at || importedAt,
    })));
    await Promise.all((payload.cash_accounts || []).map((account) => putRecord(STORE_NAMES.cashAccounts, {
        ...account,
        id: `server-cash-account-${account.id}`,
        server_id: account.id,
        sync_status: "synced",
        operation_type: "update",
        created_at: account.updated_at || importedAt,
        updated_at: account.updated_at || importedAt,
    })));
}

export async function searchProducts(query = "") {
    const q = normalizeText(query);
    const [products, variants] = await Promise.all([
        getAll(STORE_NAMES.products),
        getAll(STORE_NAMES.productVariants),
    ]);
    const variantByProduct = new Map();
    variants.forEach((variant) => {
        const list = variantByProduct.get(String(variant.product_id)) || [];
        list.push(variant);
        variantByProduct.set(String(variant.product_id), list);
    });
    return products
        .filter((product) => product.is_active !== false)
        .filter((product) => {
            if (!q) return true;
            const productText = normalizeText([product.name, product.sku, product.category].join(" "));
            const variantText = normalizeText((variantByProduct.get(String(product.server_id || product.id)) || [])
                .map((variant) => [variant.variant_sku, variant.barcode, variant.color, variant.size].join(" "))
                .join(" "));
            return productText.includes(q) || variantText.includes(q);
        })
        .slice(0, 10)
        .map((product) => ({
            id: product.server_id,
            name: product.name,
            sku: product.sku,
        }));
}

export async function variantsForProduct(productId) {
    const variants = await getAll(STORE_NAMES.productVariants);
    return variants
        .filter((variant) => String(variant.product_id) === String(productId) && variant.is_active !== false)
        .map((variant) => ({
            id: variant.server_id || variant.id,
            sku: variant.variant_sku,
            color: variant.color || "",
            size: variant.size || "",
            pieces_per_dozen: variant.pieces_per_dozen || 12,
        }));
}

export async function stockForVariant(variantId) {
    const stockRows = await getAll(STORE_NAMES.stock);
    return stockRows
        .filter((stock) => String(stock.variant_id) === String(variantId) && Number(stock.quantity || 0) > 0)
        .sort((a, b) => String(a.warehouse_name || "").localeCompare(String(b.warehouse_name || "")))
        .map((stock) => ({
            warehouse_id: stock.warehouse_id,
            warehouse_name: stock.warehouse_name,
            quantity: stock.quantity,
            min_quantity: stock.min_quantity || 0,
        }));
}

export async function priceForVariant(variantId, orderType = "b2c") {
    const variants = await getAll(STORE_NAMES.productVariants);
    const variant = variants.find((row) => String(row.server_id || row.id) === String(variantId));
    if (!variant) return "0.00";
    if (orderType === "b2b") return String(variant.wholesale_price || variant.sale_price || "0.00");
    return String(variant.retail_price || variant.sale_price || "0.00");
}

export async function searchCustomers(query = "") {
    const q = normalizeText(query);
    const customers = await getAll(STORE_NAMES.customers);
    return customers
        .filter((customer) => customer.is_active !== false && customer.operation_type !== "delete")
        .filter((customer) => {
            if (!q) return true;
            return normalizeText([customer.name, customer.phone, customer.company_name, customer.address].join(" ")).includes(q);
        })
        .slice(0, 12)
        .map((customer) => ({
            id: customer.server_id || customer.local_uuid || customer.id,
            local_uuid: customer.local_uuid || customer.id,
            name: customer.name,
            phone: customer.phone,
            customer_type: customer.customer_type || "retail",
            company_name: customer.company_name || "",
        }));
}

export async function updateStockQuantity({ variant_id, warehouse_id, delta }) {
    const id = `${warehouse_id}:${variant_id}`;
    const existing = await getRecord(STORE_NAMES.stock, id);
    if (!existing) return;
    await putRecord(STORE_NAMES.stock, {
        ...existing,
        quantity: Math.max(0, Number(existing.quantity || 0) + Number(delta || 0)),
        updated_at: nowIso(),
    });
}

export async function estimateOrderTotals(payload = {}) {
    const items = payload.items || [];
    const subtotal = items.reduce((sum, item) => sum + (Number(item.unit_price || 0) * Number(item.quantity || 0)), 0);
    const itemDiscount = items.reduce((sum, item) => {
        const base = Number(item.unit_price || 0) * Number(item.quantity || 0);
        const amount = Number(item.discount_amount || item.discount || 0);
        const percentage = Number(item.discount_percentage || 0);
        return sum + Math.min(base, amount + (base * percentage / 100));
    }, 0);
    const afterItems = Math.max(subtotal - itemDiscount, 0);
    const orderDiscount = Math.min(
        afterItems,
        Number(payload.discount_amount || payload.discount || 0) + (afterItems * Number(payload.discount_percentage || 0) / 100),
    );
    const total = Math.max(afterItems - orderDiscount, 0);
    const remaining = Math.max(total - Number(payload.paid_amount || 0), 0);
    return {
        subtotal: subtotal.toFixed(2),
        discount: (itemDiscount + orderDiscount).toFixed(2),
        total: total.toFixed(2),
        remaining_amount: remaining.toFixed(2),
    };
}
