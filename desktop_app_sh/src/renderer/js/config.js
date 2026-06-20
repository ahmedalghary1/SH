export const DEFAULT_API_BASE_URL = "https://sh.elwsamstore.com";
export const SYNC_INTERVAL_MS = 30000;

export async function getApiBaseUrl() {
  return window.desktop.settings.get("api_base_url", DEFAULT_API_BASE_URL);
}

export async function setApiBaseUrl(value) {
  const normalized = String(value || DEFAULT_API_BASE_URL).replace(/\/+$/, "");
  await window.desktop.settings.set("api_base_url", normalized);
  return normalized;
}
