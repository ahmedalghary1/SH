import { canAccessRoute, firstAllowedRoute } from "./permissions.js";
import { toast } from "./notifications.js";
import { enhanceCombos } from "./combo.js";

const routes = new Map();
let appState = {};

export function setState(next) {
  appState = { ...appState, ...next };
}

export function getState() {
  return appState;
}

export function registerRoute(name, renderer) {
  routes.set(name, renderer);
}

export async function navigate(name, params = {}) {
  const target = canAccessRoute(name) ? name : firstAllowedRoute();
  if (target !== name) {
    toast("ليست لديك صلاحية الوصول لهذه الشاشة", "warning");
  }
  const renderer = routes.get(target) || routes.get("dashboard");
  document.querySelectorAll("[data-route]").forEach((link) => {
    link.classList.toggle("active", link.dataset.route === target);
  });
  await renderer(params);
  enhanceCombos(document.getElementById("screen") || document);
}

export function routeClickHandler(event) {
  const link = event.target.closest("[data-route]");
  if (!link) return;
  event.preventDefault();
  navigate(link.dataset.route);
}
