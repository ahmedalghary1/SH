import { getApiBaseUrl, setApiBaseUrl } from "../config.js";
import { refreshNetworkStatus, isOnline } from "../networkService.js";
import { bootstrap } from "../syncService.js";
import { toast } from "../notifications.js";

export async function renderSettings() {
  const screen = document.getElementById("screen");
  const baseUrl = await getApiBaseUrl();
  const deviceId = await window.desktop.sync.deviceId();
  screen.innerHTML = `
    <div class="page-head"><h1>الإعدادات</h1></div>
    <div class="card">
      <form id="settingsForm" class="form-grid">
        <label><span>API Base URL</span><input name="api_base_url" class="ltr" value="${baseUrl}"></label>
        <label><span>Device ID</span><input class="ltr" value="${deviceId}" readonly></label>
        <button class="btn btn-primary" type="submit">حفظ الإعدادات</button>
        <button class="btn btn-light" type="button" id="checkConnection">فحص الاتصال</button>
        <button class="btn btn-secondary" type="button" id="loadBootstrap">تحميل البيانات الأساسية</button>
      </form>
    </div>
    <div class="card">حالة الاتصال: <span id="connectionStatus" class="status-pill ${isOnline() ? "status-online" : "status-offline"}">${isOnline() ? "Online" : "Offline"}</span></div>
  `;
  document.getElementById("settingsForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    await setApiBaseUrl(new FormData(event.currentTarget).get("api_base_url"));
    toast("تم حفظ الإعدادات", "success");
  });
  document.getElementById("checkConnection").addEventListener("click", async () => {
    await refreshNetworkStatus();
    renderSettings();
  });
  document.getElementById("loadBootstrap").addEventListener("click", async () => {
    try {
      await bootstrap();
      toast("تم تحميل البيانات الأساسية", "success");
    } catch (error) {
      toast(error.message || "فشل تحميل البيانات", "error");
    }
  });
}
