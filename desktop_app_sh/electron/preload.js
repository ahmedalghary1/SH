const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("desktop", {
  db: {
    init: () => ipcRenderer.invoke("db:init"),
    all: (sql, params = []) => ipcRenderer.invoke("db:all", sql, params),
    get: (sql, params = []) => ipcRenderer.invoke("db:get", sql, params),
    run: (sql, params = []) => ipcRenderer.invoke("db:run", sql, params),
    transaction: (statements = []) => ipcRenderer.invoke("db:transaction", statements)
  },
  auth: {
    saveToken: (username, token) => ipcRenderer.invoke("auth:save-token", username, token),
    getToken: (username) => ipcRenderer.invoke("auth:get-token", username),
    clearToken: (username) => ipcRenderer.invoke("auth:clear-token", username)
  },
  sync: {
    deviceId: () => ipcRenderer.invoke("sync:device-id")
  },
  settings: {
    get: (key, fallback = null) => ipcRenderer.invoke("settings:get", key, fallback),
    set: (key, value) => ipcRenderer.invoke("settings:set", key, value)
  }
});
