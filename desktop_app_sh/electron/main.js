const { app, BrowserWindow, ipcMain, safeStorage } = require("electron");
const fs = require("fs");
const path = require("path");
const { randomUUID } = require("crypto");

const { registerDbIpc } = require("./ipc/db.ipc");
const { registerAuthIpc } = require("./ipc/auth.ipc");
const { registerSyncIpc } = require("./ipc/sync.ipc");
const { registerSettingsIpc } = require("./ipc/settings.ipc");

class JsonStore {
  constructor(filePath) {
    this.filePath = filePath;
    this.data = {};
    this.load();
  }

  load() {
    try {
      this.data = JSON.parse(fs.readFileSync(this.filePath, "utf8"));
    } catch (_error) {
      this.data = {};
    }
  }

  save() {
    fs.mkdirSync(path.dirname(this.filePath), { recursive: true });
    fs.writeFileSync(this.filePath, JSON.stringify(this.data, null, 2), "utf8");
  }

  get(key, fallback = null) {
    const parts = key.split(".");
    let value = this.data;
    for (const part of parts) {
      if (!value || typeof value !== "object" || !(part in value)) return fallback;
      value = value[part];
    }
    return value;
  }

  set(key, nextValue) {
    const parts = key.split(".");
    let value = this.data;
    while (parts.length > 1) {
      const part = parts.shift();
      value[part] = value[part] && typeof value[part] === "object" ? value[part] : {};
      value = value[part];
    }
    value[parts[0]] = nextValue;
    this.save();
  }

  delete(key) {
    const parts = key.split(".");
    let value = this.data;
    while (parts.length > 1) {
      value = value?.[parts.shift()];
      if (!value) return;
    }
    delete value[parts[0]];
    this.save();
  }
}

let store;

function ensureDeviceId() {
  let deviceId = store.get("device_id");
  if (!deviceId) {
    deviceId = randomUUID();
    store.set("device_id", deviceId);
  }
  return deviceId;
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 1024,
    minHeight: 680,
    title: "SH ERP Desktop",
    backgroundColor: "#f8fafc",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  win.loadFile(path.join(__dirname, "..", "src", "renderer", "index.html"));
}

app.whenReady().then(() => {
  store = new JsonStore(path.join(app.getPath("userData"), "settings.json"));
  ensureDeviceId();
  registerDbIpc(ipcMain, app);
  registerAuthIpc(ipcMain, store, safeStorage);
  registerSyncIpc(ipcMain, store);
  registerSettingsIpc(ipcMain, store);
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
