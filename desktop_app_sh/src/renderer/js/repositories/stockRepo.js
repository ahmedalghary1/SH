import { db, nowIso } from "../db.js";

export async function replaceStock(stocks = []) {
  const statements = stocks.map((stock) => ({
    sql: `INSERT INTO local_stock(variant_server_id, warehouse_server_id, warehouse_name, quantity, min_quantity, updated_at)
          VALUES(?, ?, ?, ?, ?, ?)
          ON CONFLICT(variant_server_id, warehouse_server_id) DO UPDATE SET
            warehouse_name=excluded.warehouse_name,
            quantity=excluded.quantity,
            min_quantity=excluded.min_quantity,
            updated_at=excluded.updated_at`,
    params: [stock.variant_id, stock.warehouse_id, stock.warehouse_name || "", stock.quantity || 0, stock.min_quantity || 0, stock.updated_at || nowIso()]
  }));
  if (statements.length) await db.transaction(statements);
}

export async function decreaseStock(variantServerId, quantity) {
  const row = await db.get("SELECT * FROM local_stock WHERE variant_server_id = ? ORDER BY quantity DESC LIMIT 1", [variantServerId]);
  if (!row || Number(row.quantity) < Number(quantity)) {
    throw new Error("الكمية المحلية غير كافية");
  }
  await db.run("UPDATE local_stock SET quantity = quantity - ?, updated_at = ? WHERE id = ?", [quantity, nowIso(), row.id]);
}

export async function increaseStock(variantServerId, quantity) {
  const row = await db.get("SELECT * FROM local_stock WHERE variant_server_id = ? ORDER BY updated_at DESC LIMIT 1", [variantServerId]);
  if (!row) return;
  await db.run("UPDATE local_stock SET quantity = quantity + ?, updated_at = ? WHERE id = ?", [quantity, nowIso(), row.id]);
}
