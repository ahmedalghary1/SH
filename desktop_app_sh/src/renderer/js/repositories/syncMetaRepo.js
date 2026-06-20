import { db } from "../db.js";

export async function getMeta(key, fallback = null) {
  const row = await db.get("SELECT value FROM sync_meta WHERE key = ?", [key]);
  return row?.value ?? fallback;
}

export async function setMeta(key, value) {
  await db.run("INSERT INTO sync_meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", [key, value]);
}
