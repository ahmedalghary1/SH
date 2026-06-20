import { pingServer } from "./apiClient.js";

const listeners = new Set();
let online = navigator.onLine;

export function isOnline() {
  return online;
}

export function onNetworkChange(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function notify() {
  listeners.forEach((listener) => listener(online));
}

export async function refreshNetworkStatus() {
  online = navigator.onLine && await pingServer();
  notify();
  return online;
}

window.addEventListener("online", refreshNetworkStatus);
window.addEventListener("offline", () => {
  online = false;
  notify();
});
