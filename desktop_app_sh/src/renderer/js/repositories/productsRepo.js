import { db } from "../db.js";

export async function replaceProducts(products = [], variants = []) {
  const statements = [];
  products.forEach((product) => {
    statements.push({
      sql: `INSERT INTO products(server_id, name, sku, category, is_active, updated_at)
            VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(server_id) DO UPDATE SET
              name=excluded.name, sku=excluded.sku, category=excluded.category,
              is_active=excluded.is_active, updated_at=excluded.updated_at`,
      params: [product.id, product.name, product.sku, product.category || "", product.is_active ? 1 : 0, product.updated_at || ""]
    });
  });
  variants.forEach((variant) => {
    statements.push({
      sql: `INSERT INTO product_variants(server_id, product_server_id, color, size, variant_sku, barcode, sale_price, cost_price, image_path, is_active, updated_at)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(server_id) DO UPDATE SET
              product_server_id=excluded.product_server_id, color=excluded.color, size=excluded.size,
              variant_sku=excluded.variant_sku, barcode=excluded.barcode, sale_price=excluded.sale_price,
              cost_price=excluded.cost_price, image_path=excluded.image_path, is_active=excluded.is_active,
              updated_at=excluded.updated_at`,
      params: [variant.id, variant.product_id, variant.color || "", variant.size || "", variant.variant_sku || "", variant.barcode || "", variant.sale_price || 0, variant.cost_price || 0, variant.image_url || "", variant.is_active ? 1 : 0, variant.updated_at || ""]
    });
  });
  if (statements.length) await db.transaction(statements);
}

export async function listProducts(term = "") {
  const like = `%${term}%`;
  return db.all(
    `SELECT pv.*, p.name AS product_name, p.sku AS product_sku, COALESCE(ls.quantity, 0) AS quantity, ls.warehouse_name
     FROM product_variants pv
     JOIN products p ON p.server_id = pv.product_server_id
     LEFT JOIN local_stock ls ON ls.variant_server_id = pv.server_id
     WHERE pv.is_active = 1 AND p.is_active = 1
       AND (? = '' OR p.name LIKE ? OR p.sku LIKE ? OR pv.variant_sku LIKE ? OR pv.barcode LIKE ?)
     ORDER BY p.name, pv.color, pv.size`,
    [term, like, like, like, like]
  );
}

export async function getVariant(id) {
  return db.get(
    `SELECT pv.*, p.name AS product_name, COALESCE(ls.quantity, 0) AS quantity
     FROM product_variants pv
     JOIN products p ON p.server_id = pv.product_server_id
     LEFT JOIN local_stock ls ON ls.variant_server_id = pv.server_id
     WHERE pv.server_id = ?`,
    [id]
  );
}
