import { initDb } from "./db.js";
import { registerRoute } from "./router.js";
import { refreshNetworkStatus } from "./networkService.js";
import { restoreLastSession } from "./auth.js";
import { startSyncLoop } from "./syncService.js";
import { renderLogin } from "./screens/login.js";
import { renderShell } from "./screens/shell.js";
import { renderDashboard } from "./screens/dashboard.js";
import { renderProducts } from "./screens/products.js";
import { renderCustomers } from "./screens/customers.js";
import { renderOrders } from "./screens/orders.js";
import { renderOrderCreate } from "./screens/orderCreate.js";
import { renderPayments } from "./screens/payments.js";
import { renderReturns } from "./screens/returns.js";
import { renderSyncLog } from "./screens/syncLog.js";
import { renderSettings } from "./screens/settings.js";

registerRoute("dashboard", renderDashboard);
registerRoute("products", renderProducts);
registerRoute("customers", renderCustomers);
registerRoute("orders", renderOrders);
registerRoute("orderCreate", renderOrderCreate);
registerRoute("payments", renderPayments);
registerRoute("returns", renderReturns);
registerRoute("syncLog", renderSyncLog);
registerRoute("settings", renderSettings);

async function main() {
  await initDb();
  await refreshNetworkStatus();
  startSyncLoop();
  const user = await restoreLastSession();
  if (user) renderShell();
  else renderLogin();
}

main().catch((error) => {
  document.getElementById("app").innerHTML = `<main class="login-page"><section class="login-card"><h1>خطأ</h1><p>${error.message}</p></section></main>`;
});
