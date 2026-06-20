import { countPending } from "../repositories/syncQueueRepo.js";
import { listOrders } from "../repositories/ordersRepo.js";
import { listProducts } from "../repositories/productsRepo.js";
import { getMeta } from "../repositories/syncMetaRepo.js";
import { getCashBalance } from "../repositories/cashRepo.js";
import { runSync, bootstrap } from "../syncService.js";
import { toast } from "../notifications.js";
import { navigate } from "../router.js";
import { canAccessRoute } from "../permissions.js";

export async function renderDashboard() {
  const screen = document.getElementById("screen");
  const pending = await countPending();
  const orders = await listOrders();
  const products = await listProducts("");
  const lastSync = await getMeta("last_sync_at", "لم تتم بعد");
  const cashBalance = await getCashBalance();
  const today = new Date().toISOString().slice(0, 10);
  const todayOrders = orders.filter((order) => String(order.created_at || "").startsWith(today));
  const todaySales = todayOrders.reduce((sum, order) => sum + Number(order.total || 0), 0);
  const quickActions = [
    { route: "orderCreate", label: "فاتورة بيع جديدة", primary: true },
    { route: "customers", label: "عميل جديد" },
    { route: "payments", label: "تحصيل جديد" },
    { route: "syncLog", label: "سجل المزامنة" }
  ].filter((action) => canAccessRoute(action.route));

  screen.innerHTML = `
    <div class="page-head">
      <h1>الرئيسية</h1>
      <div class="button-row">
        <button class="btn btn-light" id="bootstrapBtn">تحميل البيانات</button>
        <button class="btn btn-primary" id="syncBtn">مزامنة الآن</button>
      </div>
    </div>
    <div class="quick-actions">
      ${quickActions.map((action) => `<button class="quick-action-btn ${action.primary ? "primary" : ""}" data-go="${action.route}">${action.label}</button>`).join("")}
    </div>
    <div class="stats-grid">
      <div class="stat-card"><div class="stat-icon">ج</div><div><span class="muted">مبيعات اليوم</span><strong class="stat-value">${todaySales.toFixed(2)}</strong></div></div>
      <div class="stat-card"><div class="stat-icon">ف</div><div><span class="muted">فواتير اليوم</span><strong class="stat-value">${todayOrders.length}</strong></div></div>
      <div class="stat-card"><div class="stat-icon">م</div><div><span class="muted">منتجات متاحة</span><strong class="stat-value">${products.length}</strong></div></div>
      <div class="stat-card"><div class="stat-icon">س</div><div><span class="muted">عمليات غير متزامنة</span><strong class="stat-value">${pending}</strong></div></div>
      <div class="stat-card"><div class="stat-icon">خ</div><div><span class="muted">رصيد الخزنة المحلية</span><strong class="stat-value">${cashBalance.toFixed(2)}</strong></div></div>
    </div>
    <div class="card"><strong>آخر مزامنة:</strong> <span class="muted ltr">${lastSync}</span></div>
  `;

  screen.querySelectorAll("[data-go]").forEach((button) => button.addEventListener("click", () => navigate(button.dataset.go)));
  document.getElementById("syncBtn").addEventListener("click", () => runSync());
  document.getElementById("bootstrapBtn").addEventListener("click", async () => {
    try {
      await bootstrap();
      toast("تم تحميل البيانات الأساسية", "success");
      renderDashboard();
    } catch (error) {
      toast(error.message || "تعذر تحميل البيانات", "error");
    }
  });
}
