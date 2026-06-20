function registerSettingsIpc(ipcMain, store) {
  ipcMain.handle("settings:get", (_event, key, fallback = null) => store.get(key, fallback));
  ipcMain.handle("settings:set", (_event, key, value) => {
    store.set(key, value);
    return { ok: true };
  });
}

module.exports = { registerSettingsIpc };
