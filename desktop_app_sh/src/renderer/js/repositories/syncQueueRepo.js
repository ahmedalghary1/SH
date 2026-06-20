import { db, nowIso } from "../db.js";

export async function enqueue({ idempotencyKey, entityType, entityLocalUuid, operationType, payload }) {
  await db.run(
    `INSERT OR IGNORE INTO sync_queue(idempotency_key, entity_type, entity_local_uuid, operation_type, payload_json, status, created_at)
     VALUES(?, ?, ?, ?, ?, 'pending', ?)`,
    [idempotencyKey, entityType, entityLocalUuid, operationType, JSON.stringify(payload), nowIso()]
  );
}

export async function pendingQueue() {
  return db.all("SELECT * FROM sync_queue WHERE status IN ('pending', 'failed') ORDER BY created_at ASC");
}

export async function allQueue() {
  return db.all("SELECT * FROM sync_queue ORDER BY created_at DESC LIMIT 200");
}

export async function markSynced(id) {
  await db.run("UPDATE sync_queue SET status = 'synced', error_message = NULL, synced_at = ?, last_attempt_at = ? WHERE id = ?", [nowIso(), nowIso(), id]);
}

export async function markFailed(id, message, status = "failed") {
  await db.run(
    "UPDATE sync_queue SET status = ?, error_message = ?, retry_count = retry_count + 1, last_attempt_at = ? WHERE id = ?",
    [status, message, nowIso(), id]
  );
}

export async function countPending() {
  const row = await db.get("SELECT COUNT(*) AS total FROM sync_queue WHERE status IN ('pending', 'failed')", []);
  return row?.total || 0;
}
