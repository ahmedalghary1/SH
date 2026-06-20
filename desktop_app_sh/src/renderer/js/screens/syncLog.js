import { allQueue } from "../repositories/syncQueueRepo.js";
import { runSync } from "../syncService.js";

export async function renderSyncLog() {
  const screen = document.getElementById("screen");
  screen.innerHTML = `
    <div class="page-head"><h1>سجل المزامنة</h1><button class="btn btn-primary" id="retrySync">إعادة المحاولة</button></div>
    <div class="table-wrap"><table><thead><tr><th>الكيان</th><th>العملية</th><th>الحالة</th><th>المحاولات</th><th>الخطأ</th><th>التاريخ</th></tr></thead><tbody id="syncBody"></tbody></table></div>
  `;
  async function load() {
    const rows = await allQueue();
    document.getElementById("syncBody").innerHTML = rows.map((row) => `
      <tr><td>${row.entity_type}</td><td>${row.operation_type}</td><td><span class="badge status-${row.status}">${row.status}</span></td><td>${row.retry_count}</td><td>${row.error_message || "-"}</td><td class="ltr">${row.created_at}</td></tr>
    `).join("") || `<tr><td colspan="6" class="empty">لا توجد عمليات مزامنة</td></tr>`;
  }
  document.getElementById("retrySync").addEventListener("click", async () => {
    await runSync();
    await load();
  });
  await load();
}
