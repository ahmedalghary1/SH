import { db, nowIso, uuid } from "../db.js";
import { enqueue } from "./syncQueueRepo.js";
import { adjustCashBalance } from "./cashRepo.js";

export async function createLocalPayment(data) {
  const localUuid = uuid();
  const now = nowIso();
  await db.run(
    `INSERT INTO payment_transactions(local_uuid, transaction_type, direction, amount, customer_server_id, customer_local_uuid, order_server_id, order_local_uuid, payment_method, notes, sync_status, created_at)
     VALUES(?, 'customer_payment', 'in', ?, ?, ?, ?, ?, ?, ?, 'pending', ?)`,
    [localUuid, data.amount, data.customer_server_id || null, data.customer_local_uuid || null, data.order_server_id || null, data.order_local_uuid || null, data.payment_method || "cash", data.notes || "", now]
  );
  const payment = await db.get("SELECT * FROM payment_transactions WHERE local_uuid = ?", [localUuid]);
  await enqueue({
    idempotencyKey: `payment-${localUuid}-create`,
    entityType: "payment",
    entityLocalUuid: localUuid,
    operationType: "create",
    payload: { payment }
  });
  await adjustCashBalance(data.amount);
  return payment;
}

export async function markPaymentSynced(localUuid, serverId) {
  await db.run("UPDATE payment_transactions SET server_id = ?, sync_status = 'synced', sync_error = NULL WHERE local_uuid = ?", [serverId, localUuid]);
}

export async function listPayments() {
  return db.all("SELECT * FROM payment_transactions ORDER BY created_at DESC LIMIT 100");
}
