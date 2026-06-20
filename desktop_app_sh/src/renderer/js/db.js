export async function initDb() {
  await window.desktop.db.init();
  await ensureColumn("orders", "created_by_server_id", "INTEGER");
  await ensureColumn("orders", "created_by_name", "TEXT");
}

async function ensureColumn(table, column, definition) {
  const columns = await window.desktop.db.all(`PRAGMA table_info(${table})`);
  if (columns.some((row) => row.name === column)) return;
  await window.desktop.db.run(`ALTER TABLE ${table} ADD COLUMN ${column} ${definition}`);
}

export const db = {
  all(sql, params = []) {
    return window.desktop.db.all(sql, params);
  },
  get(sql, params = []) {
    return window.desktop.db.get(sql, params);
  },
  run(sql, params = []) {
    return window.desktop.db.run(sql, params);
  },
  transaction(statements = []) {
    return window.desktop.db.transaction(statements);
  }
};

export function nowIso() {
  return new Date().toISOString();
}

export function uuid() {
  if (crypto.randomUUID) return crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
