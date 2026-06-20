import { listCustomers } from "../repositories/customersRepo.js";
import { createLocalPayment, listPayments } from "../repositories/paymentsRepo.js";
import { toast } from "../notifications.js";

export async function renderPayments() {
  const screen = document.getElementById("screen");
  const customers = await listCustomers("");
  screen.innerHTML = `
    <div class="page-head"><h1>التحصيلات</h1></div>
    <div class="card"><form id="paymentForm" class="form-grid">
      <label><span>العميل</span><select name="customer_local_uuid">${customers.map((c) => `<option value="${c.local_uuid}" data-server="${c.server_id || ""}">${c.name}</option>`).join("")}</select></label>
      <label><span>المبلغ</span><input name="amount" type="number" min="0.01" step="0.01" required></label>
      <label><span>طريقة التحصيل</span><select name="payment_method"><option value="cash">نقدي</option><option value="bank_transfer">تحويل</option><option value="wallet_transfer">محفظة</option></select></label>
      <label><span>ملاحظات</span><input name="notes"></label>
      <button class="btn btn-primary" type="submit">حفظ التحصيل</button>
    </form></div>
    <div class="table-wrap"><table><thead><tr><th>المبلغ</th><th>الطريقة</th><th>الحالة</th><th>التاريخ</th></tr></thead><tbody id="paymentsBody"></tbody></table></div>
  `;
  async function load() {
    const rows = await listPayments();
    document.getElementById("paymentsBody").innerHTML = rows.map((row) => `<tr><td>${row.amount}</td><td>${row.payment_method || "-"}</td><td><span class="badge status-${row.sync_status}">${row.sync_status}</span></td><td class="ltr">${row.created_at}</td></tr>`).join("") || `<tr><td colspan="4" class="empty">لا توجد تحصيلات</td></tr>`;
  }
  document.getElementById("paymentForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget).entries());
    const option = event.currentTarget.elements.customer_local_uuid.selectedOptions[0];
    data.customer_server_id = option.dataset.server || null;
    await createLocalPayment(data);
    toast("تم حفظ التحصيل محليًا بانتظار المزامنة", "success");
    event.currentTarget.reset();
    await load();
  });
  await load();
}
