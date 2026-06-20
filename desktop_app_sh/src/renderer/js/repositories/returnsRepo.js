import { db, nowIso, uuid } from "../db.js";
import { enqueue } from "./syncQueueRepo.js";
import { adjustCashBalance } from "./cashRepo.js";

export async function createLocalReturn(data) {
  const localUuid = uuid();
  const now = nowIso();
  await db.run(
    `INSERT INTO returns(local_uuid, order_server_id, order_local_uuid, return_type, status, reason, refund_amount, sync_status, created_at)
     VALUES(?, ?, ?, ?, 'draft', ?, ?, 'pending', ?)`,
    [localUuid, data.order_server_id || null, data.order_local_uuid || null, data.return_type || "partial_return", data.reason || "", data.refund_amount || 0, now]
  );
  const salesReturn = await db.get("SELECT * FROM returns WHERE local_uuid = ?", [localUuid]);
  await enqueue({
    idempotencyKey: `return-${localUuid}-create`,
    entityType: "return",
    entityLocalUuid: localUuid,
    operationType: "create",
    payload: { return: salesReturn }
  });
  await adjustCashBalance(-Number(data.refund_amount || 0));
  return salesReturn;
}

export async function listReturns() {
  return db.all("SELECT * FROM returns ORDER BY created_at DESC LIMIT 100");
}
