import { listCustomers } from "../repositories/customersRepo.js";
import { createLocalCustomer } from "../repositories/customersRepo.js";
import { listProducts } from "../repositories/productsRepo.js";
import { createLocalOrder } from "../repositories/ordersRepo.js";
import { enqueue } from "../repositories/syncQueueRepo.js";
import { getMeta } from "../repositories/syncMetaRepo.js";
import { toast } from "../notifications.js";
import { enhanceCombos } from "../combo.js";

let cart = [];

function money(value) {
  return Number(value || 0).toFixed(2);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function paymentMethodLabel(value) {
  const labels = {
    cash: "نقدي",
    credit: "آجل",
    bank_transfer: "تحويل بنكي",
    wallet_transfer: "محفظة"
  };
  return labels[value] || value || "-";
}

function paymentStatusLabel(order) {
  const remaining = Number(order.remaining_amount || 0);
  const paid = Number(order.paid_amount || 0);
  if (remaining <= 0) return "مدفوعة";
  if (paid > 0) return "مدفوعة جزئيا";
  return "غير مدفوعة";
}

async function companySettings() {
  try {
    return JSON.parse(await getMeta("company_settings", "{}") || "{}");
  } catch {
    return {};
  }
}

function renderInvoicePreview({ order, customer, items, company }) {
  const issuedAt = new Date(order.created_at || Date.now()).toLocaleString("ar-EG");
  const rows = items.map((item) => `
    <tr>
      <td>${escapeHtml(item.name)}</td>
      <td>${escapeHtml(item.color || "-")}</td>
      <td>${escapeHtml(item.size || "-")}</td>
      <td>${escapeHtml(item.warehouse_name || "-")}</td>
      <td>${money(item.quantity)}</td>
      <td>${money(item.unit_price)}</td>
      <td>${money(item.discount || 0)}</td>
      <td>${money(Number(item.quantity) * Number(item.unit_price) - Number(item.discount || 0))}</td>
    </tr>
  `).join("");

  return `
    <div class="page-head invoice-actions">
      <h1>معاينة الفاتورة</h1>
      <div class="button-row">
        <button class="btn btn-light" type="button" id="newInvoiceBtn">فاتورة جديدة</button>
        <button class="btn btn-primary" type="button" id="printInvoiceBtn">طباعة</button>
      </div>
    </div>
    <section class="invoice-box">
      <div class="invoice-head">
        <div class="invoice-brand">
          <div class="brand-mark">م</div>
          <div>
            <h1>${escapeHtml(company.name || "شركة الملابس")}</h1>
            <p>${escapeHtml(company.phone || "بيانات التواصل")}</p>
            ${company.address ? `<p>${escapeHtml(company.address)}</p>` : ""}
          </div>
        </div>
        <div class="invoice-number-box">
          <span>فاتورة</span>
          <strong>${escapeHtml(order.order_number_local || order.local_uuid)}</strong>
          <p>${issuedAt}</p>
        </div>
      </div>
      <div class="detail-grid">
        <div><span>رقم الفاتورة</span><strong>${escapeHtml(order.order_number_local || order.local_uuid)}</strong></div>
        <div><span>العميل</span><strong>${escapeHtml(customer?.name || "-")}</strong></div>
        <div><span>طريقة الدفع</span><strong>${paymentMethodLabel(order.payment_method)}</strong></div>
        <div><span>حالة الدفع</span><strong>${paymentStatusLabel(order)}</strong></div>
        <div><span>المتبقي</span><strong>${money(order.remaining_amount)}</strong></div>
        <div><span>الحالة</span><strong>${escapeHtml(order.sync_status || "pending")}</strong></div>
      </div>
      <div class="table-wrap">
        <table class="invoice-items-table">
          <thead>
            <tr><th>المنتج</th><th>اللون</th><th>المقاس</th><th>المخزن / المندوب</th><th>الكمية</th><th>السعر</th><th>الخصم</th><th>الإجمالي</th></tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <div class="invoice-totals">
        <p>الإجمالي قبل الخصم: <strong>${money(order.subtotal)}</strong></p>
        <p>الخصم: <strong>${money(order.discount)}</strong></p>
        <p>الإجمالي: <strong>${money(order.total)}</strong></p>
      </div>
      ${company.invoice_notes ? `<p class="invoice-notes">${escapeHtml(company.invoice_notes)}</p>` : ""}
      <div class="stamp">توقيع / ختم الشركة</div>
    </section>
  `;
}

export async function renderOrderCreate() {
  cart = [];
  const screen = document.getElementById("screen");
  const customers = await listCustomers("");
  const products = await listProducts("");
  const company = await companySettings();

  screen.innerHTML = `
    <div class="page-head"><h1>فاتورة بيع جديدة</h1></div>
    <div class="grid two-col">
      <div class="card">
        <h2>بيانات الصنف</h2>
        <form id="addItemForm" class="form-grid">
          <div class="inline-field">
            <label><span>العميل</span><select id="customerSelect" required>${customers.map((c) => `<option value="${c.local_uuid}">${escapeHtml(c.name)} - ${escapeHtml(c.phone || "")}</option>`).join("")}</select></label>
            <button class="btn btn-light" type="button" id="openQuickCustomer">عميل جديد</button>
          </div>
          <label><span>المنتج</span><select name="variant" required>${products.map((p) => `<option value="${p.server_id}" data-price="${p.sale_price}" data-name="${escapeHtml(p.product_name)}" data-color="${escapeHtml(p.color || "")}" data-size="${escapeHtml(p.size || "")}" data-warehouse="${escapeHtml(p.warehouse_name || "")}" data-local="${p.id}" data-qty="${p.quantity}">${escapeHtml(p.product_name)} ${escapeHtml(p.color || "")} ${escapeHtml(p.size || "")} - المتاح ${p.quantity || 0}</option>`).join("")}</select></label>
          <label><span>الكمية</span><input name="quantity" type="number" min="1" value="1" required></label>
          <button class="btn btn-light" type="submit">إضافة للصنف</button>
        </form>
      </div>
      <div class="card">
        <h2>الدفع والإجماليات</h2>
        <form id="saveOrderForm" class="form-grid">
          <label><span>طريقة الدفع</span><select name="payment_method"><option value="cash">نقدي</option><option value="credit">آجل</option><option value="bank_transfer">تحويل</option><option value="wallet_transfer">محفظة</option></select></label>
          <label><span>نوع الخصم</span><select name="discount_type" data-native-select><option value="amount">قيمة</option><option value="percentage">نسبة %</option></select></label>
          <label><span>الخصم</span><input name="discount_value" type="number" min="0" step="0.01" value="0"></label>
          <label><span>ملاحظات</span><input name="notes"></label>
          <button class="btn btn-primary" type="submit">حفظ الفاتورة</button>
        </form>
      </div>
    </div>
    <div class="table-wrap">
      <table class="invoice-items-table">
        <thead><tr><th>المنتج</th><th>اللون</th><th>المقاس</th><th>المخزن / المندوب</th><th>الكمية</th><th>السعر</th><th>الإجمالي</th><th></th></tr></thead>
        <tbody id="cartBody"></tbody>
      </table>
    </div>
    <div class="invoice-totals">
      <p>الإجمالي قبل الخصم: <strong id="cartSubtotal">0.00</strong></p>
      <p>الخصم: <strong id="cartDiscount">0.00</strong></p>
      <p>الإجمالي: <strong id="cartTotal">0.00</strong></p>
    </div>
    <div class="modal" id="quickCustomerModal" hidden>
      <div class="modal-box">
        <div class="modal-head">
          <h2>إضافة عميل سريع</h2>
          <button class="icon-btn" type="button" id="closeQuickCustomer" aria-label="إغلاق">×</button>
        </div>
        <form id="quickCustomerForm" class="form-grid">
          <label><span>اسم العميل</span><input name="name" required></label>
          <label><span>نوع العميل</span><select name="customer_type"><option value="retail">قطاعي</option><option value="wholesale">جملة</option><option value="b2c">فردي</option><option value="b2b">شركة</option></select></label>
          <label><span>الهاتف</span><input name="phone"></label>
          <label class="span-2"><span>العنوان</span><textarea name="address" rows="3"></textarea></label>
          <div class="form-actions"><button class="btn btn-primary" type="submit">حفظ العميل</button></div>
        </form>
      </div>
    </div>
  `;

  const customerSelect = document.getElementById("customerSelect");
  const quickModal = document.getElementById("quickCustomerModal");
  const openQuickCustomer = () => {
    quickModal.hidden = false;
    document.body.classList.add("modal-open");
    quickModal.querySelector("input")?.focus({ preventScroll: true });
  };
  const closeQuickCustomer = () => {
    quickModal.hidden = true;
    document.body.classList.remove("modal-open");
  };
  const discountAmount = () => {
    const subtotal = cart.reduce((sum, item) => sum + item.quantity * item.unit_price, 0);
    const type = document.querySelector("[name='discount_type']")?.value || "amount";
    const value = Number(document.querySelector("[name='discount_value']")?.value || 0);
    if (type === "percentage") return Math.min(subtotal, subtotal * Math.min(value, 100) / 100);
    return Math.min(subtotal, value);
  };

  function drawCart() {
    const subtotal = cart.reduce((sum, item) => sum + item.quantity * item.unit_price, 0);
    const discount = discountAmount();
    document.getElementById("cartSubtotal").textContent = money(subtotal);
    document.getElementById("cartDiscount").textContent = money(discount);
    document.getElementById("cartTotal").textContent = money(Math.max(subtotal - discount, 0));
    document.getElementById("cartBody").innerHTML = cart.map((item, index) => `
      <tr>
        <td>${escapeHtml(item.name)}</td>
        <td>${escapeHtml(item.color || "-")}</td>
        <td>${escapeHtml(item.size || "-")}</td>
        <td>${escapeHtml(item.warehouse_name || "-")}</td>
        <td>${money(item.quantity)}</td>
        <td>${money(item.unit_price)}</td>
        <td>${money(item.quantity * item.unit_price)}</td>
        <td><button class="btn btn-danger" data-remove="${index}" type="button">حذف</button></td>
      </tr>
    `).join("") || `<tr><td colspan="8" class="empty">أضف أصنافا للفاتورة</td></tr>`;
    document.querySelectorAll("[data-remove]").forEach((button) => button.addEventListener("click", () => {
      cart.splice(Number(button.dataset.remove), 1);
      drawCart();
    }));
  }

  document.getElementById("addItemForm").addEventListener("submit", (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const option = event.currentTarget.elements.variant.selectedOptions[0];
    const quantity = Number(form.get("quantity"));
    if (Number(option.dataset.qty) < quantity) {
      toast("الكمية المحلية غير كافية", "error");
      return;
    }
    cart.push({
      variant_server_id: Number(option.value),
      local_variant_id: Number(option.dataset.local),
      name: option.dataset.name,
      color: option.dataset.color,
      size: option.dataset.size,
      warehouse_name: option.dataset.warehouse,
      quantity,
      unit_price: Number(option.dataset.price || 0)
    });
    drawCart();
  });

  document.getElementById("openQuickCustomer").addEventListener("click", openQuickCustomer);
  document.getElementById("closeQuickCustomer").addEventListener("click", closeQuickCustomer);
  quickModal.addEventListener("click", (event) => {
    if (event.target === quickModal) closeQuickCustomer();
  });
  document.getElementById("quickCustomerForm").addEventListener("submit", async (event) => {
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
    customers.push(customer);
    const option = document.createElement("option");
    option.value = customer.local_uuid;
    option.textContent = `${customer.name} - ${customer.phone || ""}`;
    option.selected = true;
    customerSelect.appendChild(option);
    customerSelect.value = customer.local_uuid;
    customerSelect.dispatchEvent(new Event("change", { bubbles: true }));
    event.currentTarget.reset();
    closeQuickCustomer();
    toast("تم حفظ العميل محليا وإضافته للفاتورة", "success");
  });

  document.querySelector("[name='discount_type']").addEventListener("change", drawCart);
  document.querySelector("[name='discount_value']").addEventListener("input", drawCart);
  document.getElementById("saveOrderForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!cart.length) return toast("أضف صنفا واحدا على الأقل", "warning");
    const customer = customers.find((c) => c.local_uuid === document.getElementById("customerSelect").value);
    const itemsSnapshot = cart.map((item) => ({ ...item }));
    try {
      const order = await createLocalOrder({
        customer,
        items: itemsSnapshot,
        ...Object.fromEntries(new FormData(event.currentTarget).entries()),
        discount: discountAmount()
      });
      toast("تم حفظ الفاتورة محليا بانتظار المزامنة", "success");
      screen.innerHTML = renderInvoicePreview({ order, customer, items: itemsSnapshot, company });
      document.getElementById("newInvoiceBtn").addEventListener("click", renderOrderCreate);
      document.getElementById("printInvoiceBtn").addEventListener("click", () => window.print());
    } catch (error) {
      toast(error.message || "تعذر حفظ الفاتورة", "error");
    }
  });

  enhanceCombos(screen);
  drawCart();
}
