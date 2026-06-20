function encryptToken(safeStorage, token) {
  if (safeStorage.isEncryptionAvailable()) {
    return `safe:${safeStorage.encryptString(token).toString("base64")}`;
  }
  return `plain:${Buffer.from(token, "utf8").toString("base64")}`;
}

function decryptToken(safeStorage, value) {
  if (!value) return null;
  if (value.startsWith("safe:") && safeStorage.isEncryptionAvailable()) {
    return safeStorage.decryptString(Buffer.from(value.slice(5), "base64"));
  }
  if (value.startsWith("plain:")) {
    return Buffer.from(value.slice(6), "base64").toString("utf8");
  }
  return null;
}

function registerAuthIpc(ipcMain, store, safeStorage) {
  ipcMain.handle("auth:save-token", (_event, username, token) => {
    store.set(`tokens.${username}`, encryptToken(safeStorage, token));
    return { ok: true };
  });
  ipcMain.handle("auth:get-token", (_event, username) => {
    return decryptToken(safeStorage, store.get(`tokens.${username}`));
  });
  ipcMain.handle("auth:clear-token", (_event, username) => {
    store.delete(`tokens.${username}`);
    return { ok: true };
  });
}

module.exports = { registerAuthIpc };
