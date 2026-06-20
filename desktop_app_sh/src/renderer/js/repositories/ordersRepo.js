import { db, nowIso, uuid } from "../db.js";
import { enqueue } from "./syncQueueRepo.js";
import { decreaseStock } from "./stockRepo.js";
import { getCurrentUser } from "../auth.js";
import { adjustCashBalance } from "./cashRepo.js";

export async function replaceOrders(orders = []) {
  const statements = [];
  orders.forEach((order) => {
    const values = [
      order.id,
      order.local_uuid || `server-order-${order.id}`,
      order.order_number || `ORD-${order.id}`,
      order.customer_id || null,
      order.customer_local_uuid || (order.customer_id ? `server-${order.customer_id}` : null),
      order.document_type || "sale",
      order.order_type || "b2c",
      order.status || "confirmed",
      order.payment_status || "unpaid",
      order.payment_method || "cash",
      order.subtotal || 0,
      order.discount || 0,
      order.total || 0,
      order.paid_amount || 0,
      order.remaining_amount || 0,
      order.notes || "",
      order.created_by_id || null,
      order.created_by_name || "",
      order.created_at || nowIso(),
      order.updated_at || order.created_at || nowIso()
    ];
    statements.push({
      sql: `UPDATE orders SET
              local_uuid=COALESCE(NULLIF(local_uuid, ''), ?),
              order_number_local=?,
              customer_server_id=?,
              customer_local_uuid=?,
              document_type=?,
              order_type=?,
              status=?,
              payment_status=?,
              payment_method=?,
              subtotal=?,
              discount=?,
              total=?,
              paid_amount=?,
              remaining_amount=?,
              notes=?,
              created_by_server_id=?,
              created_by_name=?,
              sync_status='synced',
              sync_error=NULL,
              created_at=COALESCE(created_at, ?),
              updated_at=?
            WHERE server_id=?`,
      params: [
        values[1], values[2], values[3], values[4], values[5], values[6], values[7],
        values[8], values[9], values[10], values[11], values[12], values[13], values[14],
        values[15], values[16], values[17], values[18], values[19], values[0]
      ]
    });
    statements.push({
      sql: `INSERT INTO orders(server_id, local_uuid, order_number_local, customer_server_id, customer_local_uuid, document_type, order_type, status, payment_status, payment_method, subtotal, discount, total, paid_amount, remaining_amount, notes, created_by_server_id, created_by_name, sync_status, created_at, updated_at)
            SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'synced', ?, ?
            WHERE NOT EXISTS (SELECT 1 FROM orders WHERE server_id = ? OR local_uuid = ?)`,
      params: [...values, values[0], values[1]]
    });
  });
  if (statements.length) await db.transaction(statements);
}

export async function listOrders(filters = {}) {
  const where = [];
  const params = [];
  const term = String(filters.q || "").trim();
  if (term) {
    const like = `%${term}%`;
    where.push("(o.order_number_local LIKE ? OR c.name LIKE ? OR o.local_uuid LIKE ?)");
    params.push(like, like, like);
  }
  if (filters.status) {
    where.push("o.status = ?");
    params.push(filters.status);
  }
  if (filters.payment_method) {
    where.push("o.payment_method = ?");
    params.push(filters.payment_method);
  }
  if (filters.sync_status) {
    where.push("o.sync_status = ?");
    params.push(filters.sync_status);
  }
  if (filters.date_from) {
    where.push("date(o.created_at) >= date(?)");
    params.push(filters.date_from);
  }
  if (filters.date_to) {
    where.push("date(o.created_at) <= date(?)");
    params.push(filters.date_to);
  }
  const clause = where.length ? `WHERE ${where.join(" AND ")}` : "";
  return db.all(
    `SELECT o.*, c.name AS customer_name
     FROM orders o
     LEFT JOIN customers c ON c.local_uuid = o.customer_local_uuid
     ${clause}
     ORDER BY o.created_at DESC
     LIMIT 500`,
    params
  );
}

export async function createLocalOrder(data) {
  const {
    customer,
    items,
    notes = ""
  } = data;
  const paymentMethod = data.paymentMethod || data.payment_method || "cash";
  const paidAmount = Number(data.paidAmount ?? data.paid_amount ?? 0);
  const discount = Number(data.discount || 0);
  const user = getCurrentUser();
  const localUuid = uuid();
  const now = nowIso();
  let subtotal = 0;
  items.forEach((item) => {
    subtotal += Number(item.quantity) * Number(item.unit_price);
  });
  const total = Math.max(subtotal - discount, 0);
  const remaining = Math.max(total - paidAmount, 0);
  const paymentStatus = remaining <= 0 ? "paid" : Number(paidAmount) > 0 ? "partial" : "unpaid";

  for (const item of items) {
    await decreaseStock(item.variant_server_id, item.quantity);
  }

  const statements = [{
    sql: `INSERT INTO orders(local_uuid, order_number_local, customer_server_id, customer_local_uuid, document_type, order_type, status, payment_status, payment_method, subtotal, discount, total, paid_amount, remaining_amount, notes, created_by_server_id, created_by_name, sync_status, created_at, updated_at)
          VALUES(?, ?, ?, ?, 'sale', 'b2c', 'confirmed', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)`,
    params: [localUuid, `LOCAL-${Date.now()}`, customer.server_id || null, customer.local_uuid, paymentStatus, paymentMethod, subtotal, discount, total, paidAmount, remaining, notes, user?.id || null, user?.full_name || user?.username || "", now, now]
  }];
  items.forEach((item) => {
    statements.push({
      sql: `INSERT INTO order_items(order_local_uuid, variant_server_id, local_variant_id, quantity, unit_price, discount, total, created_at)
            VALUES(?, ?, ?, ?, ?, 0, ?, ?)`,
      params: [localUuid, item.variant_server_id, item.local_variant_id || null, item.quantity, item.unit_price, Number(item.quantity) * Number(item.unit_price), now]
    });
  });
  await db.transaction(statements);
  const order = await db.get("SELECT * FROM orders WHERE local_uuid = ?", [localUuid]);
  const savedItems = await db.all("SELECT * FROM order_items WHERE order_local_uuid = ?", [localUuid]);
  const payload = { order, items: savedItems };
  await enqueue({
    idempotencyKey: `order-${localUuid}-create`,
    entityType: "order",
    entityLocalUuid: localUuid,
    operationType: "create",
    payload
  });
  await adjustCashBalance(total);
  return order;
}

export async function markOrderSynced(localUuid, serverId) {
  await db.run("UPDATE orders SET server_id = ?, sync_status = 'synced', sync_error = NULL, updated_at = ? WHERE local_uuid = ?", [serverId, nowIso(), localUuid]);
}

export async function markOrderFailed(localUuid, message, status = "failed") {
  await db.run("UPDATE orders SET sync_status = ?, sync_error = ?, updated_at = ? WHERE local_uuid = ?", [status, message, nowIso(), localUuid]);
}
