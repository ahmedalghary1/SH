import { listProducts } from "../repositories/productsRepo.js";

export async function renderProducts() {
  const screen = document.getElementById("screen");
  screen.innerHTML = `
    <div class="page-head"><h1>المنتجات / العهدة</h1></div>
    <div class="filters"><label><span>بحث</span><input id="productSearch" placeholder="اسم المنتج أو SKU أو باركود"></label></div>
    <div class="table-wrap"><table><thead><tr><th>المنتج</th><th>اللون</th><th>المقاس</th><th>SKU</th><th>باركود</th><th>الكمية</th><th>السعر</th></tr></thead><tbody id="productsBody"></tbody></table></div>
  `;
  async function load() {
    const rows = await listProducts(document.getElementById("productSearch").value.trim());
    document.getElementById("productsBody").innerHTML = rows.length ? rows.map((row) => `
      <tr><td>${row.product_name}</td><td>${row.color || "-"}</td><td>${row.size || "-"}</td><td>${row.variant_sku || "-"}</td><td>${row.barcode || "-"}</td><td>${row.quantity || 0}</td><td>${Number(row.sale_price || 0).toFixed(2)}</td></tr>
    `).join("") : `<tr><td colspan="7" class="empty">لا توجد منتجات محلية. استخدم تحميل البيانات أولًا.</td></tr>`;
  }
  document.getElementById("productSearch").addEventListener("input", load);
  await load();
}
