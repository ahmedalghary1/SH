const fs = require("fs");
const path = require("path");

let db;
let dbPath;
let SQL;

async function openDb(app) {
  if (db) return db;
  const initSqlJs = require("sql.js");
  SQL = await initSqlJs({
    locateFile: (file) => path.join(__dirname, "..", "..", "node_modules", "sql.js", "dist", file)
  });
  const userData = app.getPath("userData");
  const dbDir = path.join(userData, "data");
  fs.mkdirSync(dbDir, { recursive: true });
  dbPath = path.join(dbDir, "sh_erp_desktop.sqlite");
  if (fs.existsSync(dbPath)) {
    db = new SQL.Database(fs.readFileSync(dbPath));
  } else {
    db = new SQL.Database();
  }
  db.run("PRAGMA foreign_keys = ON");
  const schemaPath = path.join(__dirname, "..", "..", "database", "schema.sql");
  db.run(fs.readFileSync(schemaPath, "utf8"));
  persistDb();
  return db;
}

function persistDb() {
  if (!db || !dbPath) return;
  fs.writeFileSync(dbPath, Buffer.from(db.export()));
}

function normalizeParams(params = []) {
  return Array.isArray(params) ? params : [];
}

function allRows(database, sql, params = []) {
  const stmt = database.prepare(sql);
  const rows = [];
  try {
    stmt.bind(normalizeParams(params));
    while (stmt.step()) {
      rows.push(stmt.getAsObject());
    }
  } finally {
    stmt.free();
  }
  return rows;
}

function getRow(database, sql, params = []) {
  return allRows(database, sql, params)[0] || null;
}

function runSql(database, sql, params = []) {
  database.run(sql, normalizeParams(params));
  const row = getRow(database, "SELECT last_insert_rowid() AS id");
  return {
    changes: database.getRowsModified(),
    lastInsertRowid: Number(row?.id || 0)
  };
}

function registerDbIpc(ipcMain, app) {
  ipcMain.handle("db:init", async () => {
    await openDb(app);
    return { ok: true };
  });

  ipcMain.handle("db:all", async (_event, sql, params = []) => allRows(await openDb(app), sql, params));
  ipcMain.handle("db:get", async (_event, sql, params = []) => getRow(await openDb(app), sql, params));
  ipcMain.handle("db:run", async (_event, sql, params = []) => {
    const result = runSql(await openDb(app), sql, params);
    persistDb();
    return result;
  });
  ipcMain.handle("db:transaction", async (_event, statements = []) => {
    const database = await openDb(app);
    const results = [];
    database.run("BEGIN");
    try {
      for (const item of statements) {
        results.push(runSql(database, item.sql, item.params || []));
      }
      database.run("COMMIT");
      persistDb();
      return results;
    } catch (error) {
      database.run("ROLLBACK");
      throw error;
    }
  });
}

module.exports = { registerDbIpc };
