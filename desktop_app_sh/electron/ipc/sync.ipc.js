function registerSyncIpc(ipcMain, store) {
  ipcMain.handle("sync:device-id", () => store.get("device_id"));
}

module.exports = { registerSyncIpc };
