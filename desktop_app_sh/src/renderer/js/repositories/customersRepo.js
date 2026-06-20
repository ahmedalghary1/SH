import { db, nowIso, uuid } from "../db.js";

export async function replaceCustomers(customers = []) {
  const statements = customers.map((customer) => ({
    sql: `INSERT INTO customers(server_id, local_uuid, name, phone, whatsapp, customer_type, address, credit_limit, opening_balance, is_synced, sync_status, updated_at)
          VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'synced', ?)
          ON CONFLICT(local_uuid) DO UPDATE SET
            server_id=excluded.server_id, name=excluded.name, phone=excluded.phone, whatsapp=excluded.whatsapp,
            customer_type=excluded.customer_type, address=excluded.address, credit_limit=excluded.credit_limit,
            opening_balance=excluded.opening_balance, is_synced=1, sync_status='synced', updated_at=excluded.updated_at`,
    params: [customer.id, customer.local_uuid || `server-${customer.id}`, customer.name, customer.phone || "", customer.whatsapp || "", customer.customer_type || "retail", customer.address || "", customer.credit_limit || 0, customer.opening_balance || 0, customer.updated_at || nowIso()]
  }));
  if (statements.length) await db.transaction(statements);
}

export async function listCustomers(term = "") {
  const like = `%${term}%`;
  return db.all(
    "SELECT * FROM customers WHERE deleted_at IS NULL AND (? = '' OR name LIKE ? OR phone LIKE ?) ORDER BY name",
    [term, like, like]
  );
}

export async function createLocalCustomer(data) {
  const localUuid = uuid();
  const now = nowIso();
  await db.run(
    `INSERT INTO customers(local_uuid, name, phone, whatsapp, customer_type, address, credit_limit, opening_balance, is_synced, sync_status, updated_at)
     VALUES(?, ?, ?, ?, ?, ?, ?, ?, 0, 'pending', ?)`,
    [localUuid, data.name, data.phone || "", data.whatsapp || "", data.customer_type || "retail", data.address || "", data.credit_limit || 0, data.opening_balance || 0, now]
  );
  return db.get("SELECT * FROM customers WHERE local_uuid = ?", [localUuid]);
}

export async function markCustomerSynced(localUuid, serverId) {
  await db.run("UPDATE customers SET server_id = ?, is_synced = 1, sync_status = 'synced', sync_error = NULL, updated_at = ? WHERE local_uuid = ?", [serverId, nowIso(), localUuid]);
}
