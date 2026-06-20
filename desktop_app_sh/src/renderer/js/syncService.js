import { apiFetch } from "./apiClient.js";
import { isOnline, onNetworkChange, refreshNetworkStatus } from "./networkService.js";
import { toast } from "./notifications.js";
import { pendingQueue, markSynced, markFailed } from "./repositories/syncQueueRepo.js";
import { markCustomerSynced, replaceCustomers } from "./repositories/customersRepo.js";
import { replaceProducts } from "./repositories/productsRepo.js";
import { replaceStock } from "./repositories/stockRepo.js";
import { markOrderFailed, markOrderSynced, replaceOrders } from "./repositories/ordersRepo.js";
import { markPaymentSynced } from "./repositories/paymentsRepo.js";
import { setMeta, getMeta } from "./repositories/syncMetaRepo.js";
import { SYNC_INTERVAL_MS } from "./config.js";
import { applyServerUser } from "./auth.js";

let running = false;
let timer = null;

export async function bootstrap() {
  const payload = await apiFetch("/api/sync/bootstrap/");
  await applyServerUser(payload.user);
  await replaceProducts(payload.products || [], payload.variants || []);
  await replaceCustomers(payload.customers || []);
  await replaceOrders(payload.orders || []);
  await replaceStock(payload.stock || []);
  await setMeta("company_settings", JSON.stringify(payload.company || {}));
  await setMeta("permissions", JSON.stringify(payload.permissions || {}));
  if (payload.cash?.balance !== undefined) await setMeta("local_cash_balance", String(payload.cash.balance));
  await setMeta("last_sync_at", new Date().toISOString());
  return payload;
}

function sortQueue(items) {
  const order = { customer: 1, order: 2, payment: 3, return: 4, stock_movement: 5 };
  return [...items].sort((a, b) => (order[a.entity_type] || 99) - (order[b.entity_type] || 99));
}

async function applySuccess(item, result) {
  if (item.entity_type === "customer") await markCustomerSynced(item.entity_local_uuid, result.server_id);
  if (item.entity_type === "order") await markOrderSynced(item.entity_local_uuid, result.server_id);
  if (item.entity_type === "payment") await markPaymentSynced(item.entity_local_uuid, result.server_id);
}

async function applyFailure(item, result) {
  const status = result.status === "failed_conflict" ? "conflict" : "failed";
  if (item.entity_type === "order") await markOrderFailed(item.entity_local_uuid, result.error || "فشلت المزامنة", status);
  await markFailed(item.id, result.error || "فشلت المزامنة", status);
}

export async function runSync({ silent = false } = {}) {
  if (running) return { skipped: true };
  if (!isOnline()) {
    if (!silent) toast("لا يوجد اتصال بالإنترنت، سيتم الحفظ محليًا", "warning");
    return { offline: true };
  }
  running = true;
  try {
    const items = sortQueue(await pendingQueue());
    for (const item of items) {
      const operation = {
        idempotency_key: item.idempotency_key,
        entity_type: item.entity_type,
        operation_type: item.operation_type,
        local_uuid: item.entity_local_uuid,
        device_id: await window.desktop.sync.deviceId(),
        created_at: item.created_at,
        payload: JSON.parse(item.payload_json)
      };
      const results = await apiFetch("/api/sync/push/", {
        method: "POST",
        body: JSON.stringify([operation])
      });
      const result = results[0];
      if (result.status === "success") {
        await applySuccess(item, result);
        await markSynced(item.id);
      } else {
        await applyFailure(item, result);
      }
    }
    if (items.length) {
      await pullChanges();
      if (!silent) toast("تمت المزامنة بنجاح", "success");
    }
    return { synced: items.length };
  } catch (error) {
    if (!silent) toast(error.message || "فشلت المزامنة", "error");
    return { error };
  } finally {
    running = false;
  }
}

export async function pullChanges() {
  const since = await getMeta("last_sync_at", "");
  const changes = await apiFetch(`/api/sync/changes/?since=${encodeURIComponent(since)}`);
  await applyServerUser(changes.user);
  await replaceProducts(changes.products || [], changes.variants || []);
  await replaceCustomers(changes.customers || []);
  await replaceOrders(changes.orders || []);
  await replaceStock(changes.stock || []);
  await setMeta("company_settings", JSON.stringify(changes.company || {}));
  await setMeta("permissions", JSON.stringify(changes.permissions || {}));
  if (changes.cash?.balance !== undefined) await setMeta("local_cash_balance", String(changes.cash.balance));
  await setMeta("last_sync_at", new Date().toISOString());
  return changes;
}

export function startSyncLoop() {
  if (timer) clearInterval(timer);
  timer = setInterval(async () => {
    await refreshNetworkStatus();
    await runSync({ silent: true });
  }, SYNC_INTERVAL_MS);
  onNetworkChange((online) => {
    if (online) runSync({ silent: false });
  });
}
