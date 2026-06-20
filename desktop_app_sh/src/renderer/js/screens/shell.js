import { getCurrentUser, logout } from "../auth.js";
import { isOnline, onNetworkChange } from "../networkService.js";
import { navigate, routeClickHandler } from "../router.js";
import { canAccessRoute, firstAllowedRoute, isManager, roleLabel } from "../permissions.js";

let listensForUserUpdates = false;
let listensForRouteClicks = false;

function navLink(route, label, iconClass = "color-blue", extraClass = "") {
  if (!canAccessRoute(route)) return "";
  return `
    <a class="nav-link ${extraClass}" href="#" data-route="${route}">
      <span class="nav-icon ${iconClass}"></span>
      <span class="nav-text">${label}</span>
      <span class="nav-arrow">‹</span>
    </a>
  `;
}

function navGroup(label, iconClass, links) {
  const visibleLinks = links.filter((link) => canAccessRoute(link.route));
  if (!visibleLinks.length) return "";
  return `
    <div class="nav-group">
      <button class="nav-group-toggle" type="button" data-nav-group-toggle aria-expanded="false">
        <span class="nav-icon ${iconClass}"></span>
        <span class="nav-text">${label}</span>
        <span class="nav-chevron" aria-hidden="true">‹</span>
      </button>
      <div class="nav-group-panel">
        ${visibleLinks.map((link) => navLink(link.route, link.label, iconClass)).join("")}
      </div>
    </div>
  `;
}

export function renderShell() {
  const user = getCurrentUser();
  const startRoute = firstAllowedRoute();
  const settingsGroup = isManager()
    ? navGroup("الإعدادات", "color-gray", [{ route: "settings", label: "الإعدادات العامة" }])
    : "";

  document.getElementById("app").innerHTML = `
    <div class="sidebar-backdrop" data-sidebar-close></div>
    <div class="app-shell">
      <aside class="sidebar">
        <div class="brand">
          <div class="brand-mark">م</div>
          <div><strong>إدارة الملابس</strong><span>مبيعات ومخازن</span></div>
        </div>
        <nav class="side-nav" aria-label="القائمة الرئيسية">
          ${navLink("dashboard", "الرئيسية", "color-red", "nav-single")}
          ${navGroup("المنتجات", "color-cyan", [
            { route: "products", label: "المنتجات / العهدة" }
          ])}
          ${navGroup("المبيعات", "color-green", [
            { route: "orders", label: "الفواتير" },
            { route: "orderCreate", label: "فاتورة جديدة" },
            { route: "returns", label: "المرتجع" },
            { route: "customers", label: "العملاء" },
            { route: "payments", label: "التحصيلات" }
          ])}
          ${settingsGroup}
          ${navLink("syncLog", "سجل المزامنة", "color-blue", "nav-single")}
        </nav>
      </aside>
      <main class="main-area">
        <header class="topbar">
          <button class="icon-btn menu-toggle" id="sidebarToggle" type="button" title="القائمة">☰</button>
          <div class="topbar-user">
            <strong>${user?.full_name || user?.username || "-"}</strong>
            <span>${roleLabel(user?.role)}</span>
          </div>
          <span id="networkPill" class="status-pill"></span>
          <button class="btn btn-secondary" id="logoutBtn">تسجيل الخروج</button>
        </header>
        <section class="page-content" id="screen"></section>
      </main>
    </div>
  `;

  if (!listensForRouteClicks) {
    listensForRouteClicks = true;
    document.addEventListener("click", routeClickHandler);
  }
  document.getElementById("logoutBtn").addEventListener("click", async () => {
    await logout();
    location.reload();
  });
  document.getElementById("sidebarToggle").addEventListener("click", () => document.body.classList.toggle("sidebar-open"));
  document.querySelector("[data-sidebar-close]").addEventListener("click", () => document.body.classList.remove("sidebar-open"));
  document.querySelectorAll("[data-nav-group-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const group = button.closest(".nav-group");
      const isOpen = group.classList.toggle("is-open");
      button.setAttribute("aria-expanded", String(isOpen));
    });
  });

  const updatePill = () => {
    const pill = document.getElementById("networkPill");
    pill.className = `status-pill ${isOnline() ? "status-online" : "status-offline"}`;
    pill.textContent = isOnline() ? "Online" : "Offline";
  };
  updatePill();
  onNetworkChange(updatePill);
  if (!listensForUserUpdates) {
    listensForUserUpdates = true;
    window.addEventListener("auth:user-updated", () => renderShell());
  }
  navigate(startRoute);
}
