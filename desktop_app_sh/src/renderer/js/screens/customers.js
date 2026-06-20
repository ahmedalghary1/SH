import { createLocalCustomer, listCustomers } from "../repositories/customersRepo.js";
import { enqueue } from "../repositories/syncQueueRepo.js";
import { toast } from "../notifications.js";

export async function renderCustomers() {
  const screen = document.getElementById("screen");
  screen.innerHTML = `
    <div class="page-head"><h1>العملاء</h1></div>
    <div class="card">
      <form id="customerForm" class="form-grid">
        <label><span>اسم العميل</span><input name="name" required></label>
        <label><span>الهاتف</span><input name="phone"></label>
        <label><span>واتساب</span><input name="whatsapp"></label>
        <label><span>النوع</span><select name="customer_type"><option value="retail">قطاعي</option><option value="wholesale">جملة</option><option value="b2c">فردي</option><option value="b2b">شركة</option></select></label>
        <label><span>العنوان</span><input name="address"></label>
        <button class="btn btn-primary" type="submit">حفظ عميل محلي</button>
      </form>
    </div>
    <div class="filters"><label><span>بحث</span><input id="customerSearch"></label></div>
    <div class="table-wrap"><table><thead><tr><th>الاسم</th><th>الهاتف</th><th>النوع</th><th>الحالة</th></tr></thead><tbody id="customersBody"></tbody></table></div>
  `;
  async function load() {
    const rows = await listCustomers(document.getElementById("customerSearch").value.trim());
    document.getElementById("customersBody").innerHTML = rows.map((row) => `
      <tr><td>${row.name}</td><td>${row.phone || "-"}</td><td>${row.customer_type || "-"}</td><td><span class="badge status-${row.sync_status || "synced"}">${row.sync_status || "synced"}</span></td></tr>
    `).join("") || `<tr><td colspan="4" class="empty">لا يوجد عملاء</td></tr>`;
  }
  document.getElementById("customerSearch").addEventListener("input", load);
  document.getElementById("customerForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget).entries());
    const customer = await createLocalCustomer(data);
    await enqueue({
      idempotencyKey: `customer-${customer.local_uuid}-create`,
      entityType: "customer",
      entityLocalUuid: customer.local_uuid,
      operationType: "create",
      payload: { customer }
    });
    event.currentTarget.reset();
    toast("تم حفظ العميل محليًا بانتظار المزامنة", "success");
    await load();
  });
  await load();
}
