import { db, nowIso } from "../db.js";

export async function saveUser(user) {
  const now = nowIso();
  await db.run(
    `INSERT INTO users(server_id, username, full_name, role, permissions_json, last_login_at, created_at, updated_at)
     VALUES(?, ?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(username) DO UPDATE SET
       server_id=excluded.server_id,
       full_name=excluded.full_name,
       role=excluded.role,
       permissions_json=excluded.permissions_json,
       last_login_at=excluded.last_login_at,
       updated_at=excluded.updated_at`,
    [
      user.id,
      user.username,
      user.full_name || user.username,
      user.role,
      JSON.stringify(user.permissions || {}),
      now,
      now,
      now
    ]
  );
}

export async function getUserByUsername(username) {
  return db.get("SELECT * FROM users WHERE username = ?", [username]);
}

export async function getLastUser() {
  return db.get("SELECT * FROM users ORDER BY last_login_at DESC LIMIT 1");
}
