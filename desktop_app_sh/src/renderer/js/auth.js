import { apiFetch, setAuthToken } from "./apiClient.js";
import { isOnline } from "./networkService.js";
import { saveUser, getUserByUsername, getLastUser } from "./repositories/usersRepo.js";

let currentUser = null;

export function getCurrentUser() {
  return currentUser;
}

export async function applyServerUser(user) {
  if (!user) return currentUser;
  const previousRole = currentUser?.role;
  const previousPermissions = JSON.stringify(currentUser?.permissions || {});
  await saveUser(user);
  currentUser = user;
  if (previousRole !== user.role || previousPermissions !== JSON.stringify(user.permissions || {})) {
    window.dispatchEvent(new CustomEvent("auth:user-updated", { detail: user }));
  }
  return currentUser;
}

export async function restoreLastSession() {
  const user = await getLastUser();
  if (!user) return null;
  const token = await window.desktop.auth.getToken(user.username);
  if (!token) return null;
  setAuthToken(token);
  currentUser = {
    id: user.server_id,
    username: user.username,
    full_name: user.full_name,
    role: user.role,
    permissions: JSON.parse(user.permissions_json || "{}")
  };
  if (isOnline()) {
    try {
      const deviceId = await window.desktop.sync.deviceId();
      const data = await apiFetch("/api/auth/refresh/", {
        method: "POST",
        body: JSON.stringify({ device_id: deviceId })
      });
      setAuthToken(data.token);
      await window.desktop.auth.saveToken(data.user.username, data.token);
      await saveUser(data.user);
      currentUser = data.user;
    } catch (_error) {
      setAuthToken(token);
    }
  }
  return currentUser;
}

export async function login(username, password) {
  if (isOnline()) {
    const deviceId = await window.desktop.sync.deviceId();
    const data = await apiFetch("/api/auth/login/", {
      method: "POST",
      body: JSON.stringify({ username, password, device_id: deviceId })
    });
    setAuthToken(data.token);
    await window.desktop.auth.saveToken(username, data.token);
    await saveUser(data.user);
    currentUser = data.user;
    return currentUser;
  }

  const user = await getUserByUsername(username);
  if (!user) throw new Error("لا يوجد تسجيل دخول سابق لهذا المستخدم على الجهاز");
  const token = await window.desktop.auth.getToken(username);
  if (!token) throw new Error("لا توجد جلسة محفوظة لهذا المستخدم");
  setAuthToken(token);
  currentUser = {
    id: user.server_id,
    username: user.username,
    full_name: user.full_name,
    role: user.role,
    permissions: JSON.parse(user.permissions_json || "{}")
  };
  return currentUser;
}

export async function logout() {
  currentUser = null;
  setAuthToken(null);
}
