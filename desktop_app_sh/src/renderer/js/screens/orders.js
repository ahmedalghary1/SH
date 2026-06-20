import { listOrders } from "../repositories/ordersRepo.js";
import { navigate } from "../router.js";
import { isManager } from "../permissions.js";

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function money(value) {
  return Number(value || 0).toFixed(2);
}

function statusLabel(value) {
  const labels = {
    draft: "مسودة",
    confirmed: "مؤكد",
    preparing: "قيد التجهيز",
    ready: "جاهز",
    completed: "مكتمل",
    cancelled: "ملغي",
    partially_returned: "مرتجع جزئيا",
    returned: "مرتجع"
  };
  return labels[value] || value || "-";
}

function orderTypeLabel(value) {
  const labels = {
    b2c: "قطاعي",
    b2b: "جملة"
  };
  return labels[value] || value || "-";
}

function paymentLabel(value) {
  const labels = {
    cash: "نقدي",
    cod: "عند الاستلام",
    bank_transfer: "تحويل بنكي",
    wallet_transfer: "محفظة",
    credit: "آجل"
  };
  return labels[value] || value || "-";
}

function syncLabel(value) {
  const labels = {
    synced: "متزامنة",
    pending: "بانتظار المزامنة",
    failed: "فشلت",
    conflict: "تعارض"
  };
  return labels[value] || value || "-";
}

function collectFilters(form) {
  return Object.fromEntries(new FormData(form).entries());
}

export async function renderOrders() {
  const screen = document.getElementById("screen");
  const scopeText = isManager() ? "كل الفواتير" : "فواتير المندوب";

  screen.innerHTML = `
    <div class="page-head">
      <div>
        <h1>الفواتير</h1>
        <p class="muted">${scopeText}</p>
      </div>
      <button class="btn btn-accent" id="addOrderBtn" type="button">إضافة فاتورة</button>
    </div>
    <form class="filters" id="ordersFilters">
      <label><span>بحث</span><input name="q" placeholder="رقم الفاتورة أو العميل"></label>
      <label><span>الحالة</span><select name="status"><option value="">كل الحالات</option><option value="draft">مسودة</option><option value="confirmed">مؤكد</option><option value="preparing">قيد التجهيز</option><option value="ready">جاهز</option><option value="completed">مكتمل</option><option value="cancelled">ملغي</option><option value="partially_returned">مرتجع جزئيا</option><option value="returned">مرتجع</option></select></label>
      <label><span>طريقة الدفع</span><select name="payment_method"><option value="">كل الطرق</option><option value="cash">نقدي</option><option value="credit">آجل</option><option value="bank_transfer">تحويل بنكي</option><option value="wallet_transfer">محفظة</option><option value="cod">عند الاستلام</option></select></label>
      <label><span>المزامنة</span><select name="sync_status"><option value="">كل الحالات</option><option value="synced">متزامنة</option><option value="pending">بانتظار المزامنة</option><option value="failed">فشلت</option><option value="conflict">تعارض</option></select></label>
      <label><span>من تاريخ</span><input name="date_from" type="date"></label>
      <label><span>إلى تاريخ</span><input name="date_to" type="date"></label>
      <button class="btn btn-primary" type="submit">بحث</button>
      <button class="btn btn-light" id="clearFilters" type="button">مسح</button>
    </form>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>رقم الفاتورة</th>
            <th>النوع</th>
            <th>العميل</th>
            <th>الحالة</th>
            <th>طريقة الدفع</th>
            <th>الإجمالي</th>
            <th>الخصم</th>
            <th>الموظف</th>
            <th>المزامنة</th>
            <th>التاريخ</th>
          </tr>
        </thead>
        <tbody id="ordersBody"></tbody>
      </table>
    </div>
  `;

  async function load() {
    const rows = await listOrders(collectFilters(document.getElementById("ordersFilters")));
    document.getElementById("ordersBody").innerHTML = rows.map((row) => `
      <tr>
        <td>${escapeHtml(row.order_number_local || row.local_uuid)}</td>
        <td>${orderTypeLabel(row.order_type)}</td>
        <td>${escapeHtml(row.customer_name || "-")}</td>
        <td><span class="badge status-${escapeHtml(row.status || "confirmed")}">${statusLabel(row.status)}</span></td>
        <td>${paymentLabel(row.payment_method)}</td>
        <td>${money(row.total)}</td>
        <td>${money(row.discount)}</td>
        <td>${escapeHtml(row.created_by_name || "-")}</td>
        <td><span class="badge status-${escapeHtml(row.sync_status || "pending")}">${syncLabel(row.sync_status)}</span></td>
        <td class="ltr">${escapeHtml(String(row.created_at || "").slice(0, 16).replace("T", " "))}</td>
      </tr>
    `).join("") || `<tr><td colspan="10" class="empty">لا توجد فواتير</td></tr>`;
  }

  document.getElementById("addOrderBtn").addEventListener("click", () => navigate("orderCreate"));
  document.getElementById("ordersFilters").addEventListener("submit", async (event) => {
    event.preventDefault();
    await load();
  });
  document.getElementById("clearFilters").addEventListener("click", async () => {
    document.getElementById("ordersFilters").reset();
    await load();
  });
  document.getElementById("ordersFilters").querySelectorAll("input, select").forEach((input) => {
    input.addEventListener("change", load);
  });
  await load();
}
