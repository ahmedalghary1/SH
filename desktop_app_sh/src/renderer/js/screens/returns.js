import { listOrders } from "../repositories/ordersRepo.js";
import { createLocalReturn, listReturns } from "../repositories/returnsRepo.js";
import { toast } from "../notifications.js";

export async function renderReturns() {
  const screen = document.getElementById("screen");
  const orders = await listOrders();
  screen.innerHTML = `
    <div class="page-head"><h1>المرتجعات</h1></div>
    <div class="card"><form id="returnForm" class="form-grid">
      <label><span>الفاتورة</span><select name="order_local_uuid">${orders.map((o) => `<option value="${o.local_uuid}" data-server="${o.server_id || ""}">${o.order_number_local || o.local_uuid} - ${o.customer_name || ""}</option>`).join("")}</select></label>
      <label><span>نوع المرتجع</span><select name="return_type"><option value="partial_return">مرتجع جزئي</option><option value="refund">استرداد</option><option value="exchange">استبدال</option></select></label>
      <label><span>قيمة الاسترداد</span><input name="refund_amount" type="number" min="0" step="0.01" value="0"></label>
      <label><span>السبب</span><input name="reason"></label>
      <button class="btn btn-primary" type="submit">حفظ المرتجع</button>
    </form></div>
    <div class="table-wrap"><table><thead><tr><th>الفاتورة</th><th>النوع</th><th>الحالة</th><th>التاريخ</th></tr></thead><tbody id="returnsBody"></tbody></table></div>
  `;
  async function load() {
    const rows = await listReturns();
    document.getElementById("returnsBody").innerHTML = rows.map((row) => `<tr><td>${row.order_local_uuid || row.order_server_id}</td><td>${row.return_type}</td><td><span class="badge status-${row.sync_status}">${row.sync_status}</span></td><td class="ltr">${row.created_at}</td></tr>`).join("") || `<tr><td colspan="4" class="empty">لا توجد مرتجعات</td></tr>`;
  }
  document.getElementById("returnForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget).entries());
    const option = event.currentTarget.elements.order_local_uuid.selectedOptions[0];
    data.order_server_id = option.dataset.server || null;
    await createLocalReturn(data);
    toast("تم حفظ المرتجع محليًا بانتظار المزامنة", "success");
    event.currentTarget.reset();
    await load();
  });
  await load();
}
