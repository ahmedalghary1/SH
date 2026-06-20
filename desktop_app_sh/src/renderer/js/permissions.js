import { getCurrentUser } from "./auth.js";

export function userRole(user = getCurrentUser()) {
  return user?.role || "";
}

export function isManager(user = getCurrentUser()) {
  const role = userRole(user);
  return Boolean(user?.permissions?.is_manager || role === "manager" || role === "director");
}

export function isSales(user = getCurrentUser()) {
  return userRole(user) === "sales";
}

export function isWarehouse(user = getCurrentUser()) {
  return userRole(user) === "warehouse";
}

export function hasRole(...roles) {
  const user = getCurrentUser();
  if (!user) return false;
  if (isManager(user)) return true;
  return roles.includes(userRole(user));
}

export function canAccessRoute(routeName) {
  const rules = {
    dashboard: () => hasRole("sales", "warehouse"),
    products: () => hasRole("warehouse"),
    orders: () => hasRole("sales"),
    orderCreate: () => hasRole("sales"),
    customers: () => hasRole("sales"),
    payments: () => hasRole("sales"),
    returns: () => isManager(),
    syncLog: () => hasRole("sales", "warehouse"),
    settings: () => isManager()
  };
  return (rules[routeName] || rules.dashboard)();
}

export function firstAllowedRoute() {
  return ["dashboard", "orders", "orderCreate", "products", "customers", "payments", "returns", "syncLog", "settings"].find(canAccessRoute) || "dashboard";
}

export function roleLabel(role = userRole()) {
  const labels = {
    manager: "مسؤول النظام",
    director: "المدير",
    sales: "مندوب مبيعات",
    warehouse: "مسؤول مخزن"
  };
  return labels[role] || role || "-";
}
