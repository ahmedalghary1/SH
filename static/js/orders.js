(function () {
    const form = document.getElementById("order-form");
    if (!form) return;

    const searchInput = document.getElementById("product-search");
    const resultsBox = document.getElementById("product-results");
    const variantSelect = document.getElementById("variant-select");
    const stockInput = document.getElementById("available-stock");
    const priceInput = document.getElementById("unit-price");
    const qtyInput = document.getElementById("item-quantity");
    const discountInput = document.getElementById("item-discount");
    const addButton = document.getElementById("add-item");
    const body = document.getElementById("order-items-body");
    const itemsJson = document.getElementById("items-json");
    const orderType = document.getElementById("id_order_type");
    const warehouse = document.getElementById("id_warehouse");
    const paidAmount = document.getElementById("id_paid_amount");
    const generalDiscount = document.getElementById("id_discount");
    const customerSelect = document.getElementById("id_customer");
    const customerSearch = document.getElementById("customer-search");
    const customerResults = document.getElementById("customer-results");
    const items = [];
    let selectedProduct = null;

    function money(value) {
        return Number(value || 0).toFixed(2);
    }

    function updateSummary() {
        const subtotal = items.reduce((sum, item) => sum + (Number(item.unit_price) * Number(item.quantity)), 0);
        const lineDiscount = items.reduce((sum, item) => sum + Number(item.discount || 0), 0);
        const discount = lineDiscount + Number(generalDiscount.value || 0);
        const total = Math.max(subtotal - discount, 0);
        const paid = Number(paidAmount.value || 0);
        const remaining = Math.max(total - paid, 0);
        document.getElementById("summary-subtotal").textContent = money(subtotal);
        document.getElementById("summary-discount").textContent = money(discount);
        document.getElementById("summary-total").textContent = money(total);
        document.getElementById("summary-paid").textContent = money(paid);
        document.getElementById("summary-remaining").textContent = money(remaining);
        itemsJson.value = JSON.stringify(items);
    }

    function renderItems() {
        body.innerHTML = "";
        if (!items.length) {
            body.innerHTML = '<tr class="empty-row"><td colspan="8">لم تتم إضافة منتجات بعد</td></tr>';
            updateSummary();
            return;
        }
        items.forEach((item, index) => {
            const total = Math.max((Number(item.unit_price) * Number(item.quantity)) - Number(item.discount || 0), 0);
            const row = document.createElement("tr");
            row.innerHTML = `
                <td>${item.product_name}</td>
                <td>${item.color || "-"}</td>
                <td>${item.size || "-"}</td>
                <td>${item.quantity}</td>
                <td>${money(item.unit_price)}</td>
                <td>${money(item.discount)}</td>
                <td>${money(total)}</td>
                <td><button type="button" class="btn btn-danger" data-remove="${index}">حذف</button></td>
            `;
            body.appendChild(row);
        });
        updateSummary();
    }

    async function fetchJson(url, options) {
        const response = await fetch(url, options);
        return response.json();
    }

    searchInput.addEventListener("input", async () => {
        const q = searchInput.value.trim();
        if (q.length < 2) {
            resultsBox.classList.remove("is-open");
            return;
        }
        const data = await fetchJson(`/orders/ajax/search-products/?q=${encodeURIComponent(q)}`);
        resultsBox.innerHTML = "";
        data.data.forEach((product) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "search-result";
            button.textContent = `${product.name} - ${product.sku}`;
            button.dataset.id = product.id;
            button.dataset.name = product.name;
            resultsBox.appendChild(button);
        });
        resultsBox.classList.add("is-open");
    });

    resultsBox.addEventListener("click", async (event) => {
        const button = event.target.closest(".search-result");
        if (!button) return;
        selectedProduct = { id: button.dataset.id, name: button.dataset.name };
        searchInput.value = button.textContent;
        resultsBox.classList.remove("is-open");
        const data = await fetchJson(`/orders/ajax/products/${selectedProduct.id}/variants/`);
        variantSelect.innerHTML = '<option value="">اختر المتغير</option>';
        data.data.forEach((variant) => {
            const option = document.createElement("option");
            option.value = variant.id;
            option.textContent = `${variant.color || "-"} / ${variant.size || "-"} - ${variant.sku}`;
            option.dataset.color = variant.color;
            option.dataset.size = variant.size;
            variantSelect.appendChild(option);
        });
    });

    customerSearch?.addEventListener("input", async () => {
        const q = customerSearch.value.trim();
        if (q.length < 2) {
            customerResults.classList.remove("is-open");
            return;
        }
        const data = await fetchJson(`/orders/ajax/search-customers/?q=${encodeURIComponent(q)}`);
        customerResults.innerHTML = "";
        data.data.forEach((customer) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "search-result";
            button.textContent = `${customer.name} - ${customer.phone}`;
            button.dataset.id = customer.id;
            button.dataset.name = customer.name;
            button.dataset.phone = customer.phone;
            customerResults.appendChild(button);
        });
        customerResults.classList.add("is-open");
    });

    customerResults?.addEventListener("click", (event) => {
        const button = event.target.closest(".search-result");
        if (!button) return;
        let option = customerSelect.querySelector(`option[value="${button.dataset.id}"]`);
        if (!option) {
            option = document.createElement("option");
            option.value = button.dataset.id;
            option.textContent = `${button.dataset.name} - ${button.dataset.phone}`;
            customerSelect.appendChild(option);
        }
        option.selected = true;
        customerSearch.value = option.textContent;
        customerResults.classList.remove("is-open");
    });

    async function refreshVariantMeta() {
        const variantId = variantSelect.value;
        if (!variantId || !warehouse.value) return;
        const stock = await fetchJson(`/orders/ajax/variants/${variantId}/stock/?warehouse_id=${warehouse.value}`);
        stockInput.value = stock.data.quantity;
        const price = await fetchJson(`/orders/ajax/variants/${variantId}/price/?order_type=${orderType.value}`);
        priceInput.value = price.data.price;
    }

    variantSelect.addEventListener("change", refreshVariantMeta);
    warehouse.addEventListener("change", refreshVariantMeta);
    orderType.addEventListener("change", refreshVariantMeta);
    paidAmount.addEventListener("input", updateSummary);
    generalDiscount.addEventListener("input", updateSummary);

    addButton.addEventListener("click", () => {
        const selected = variantSelect.options[variantSelect.selectedIndex];
        const quantity = Number(qtyInput.value || 0);
        const available = Number(stockInput.value || 0);
        if (!selectedProduct || !variantSelect.value) {
            window.alert("اختر المنتج والمتغير أولًا");
            return;
        }
        if (quantity <= 0 || quantity > available) {
            window.alert("الكمية غير متاحة");
            return;
        }
        items.push({
            variant_id: variantSelect.value,
            product_name: selectedProduct.name,
            color: selected.dataset.color,
            size: selected.dataset.size,
            quantity,
            unit_price: Number(priceInput.value || 0),
            discount: Number(discountInput.value || 0),
        });
        renderItems();
        qtyInput.value = 1;
        discountInput.value = 0;
    });

    body.addEventListener("click", (event) => {
        const remove = event.target.closest("[data-remove]");
        if (!remove) return;
        items.splice(Number(remove.dataset.remove), 1);
        renderItems();
    });

    form.addEventListener("submit", (event) => {
        if (!items.length) {
            event.preventDefault();
            window.alert("أضف منتجًا واحدًا على الأقل");
        }
    });

    document.getElementById("quick-customer-save")?.addEventListener("click", async () => {
        const payload = new FormData();
        payload.append("name", document.getElementById("quick-customer-name").value);
        payload.append("customer_type", document.getElementById("quick-customer-type").value);
        payload.append("phone", document.getElementById("quick-customer-phone").value);
        payload.append("whatsapp", document.getElementById("quick-customer-whatsapp").value);
        payload.append("company_name", document.getElementById("quick-customer-company").value);
        payload.append("tax_number", document.getElementById("quick-customer-tax").value);
        payload.append("address", document.getElementById("quick-customer-address").value);
        payload.append("is_active", "on");
        const data = await fetchJson("/customers/ajax/quick-create/", {
            method: "POST",
            headers: { "X-CSRFToken": getCookie("csrftoken") },
            body: payload,
        });
        if (!data.success) {
            window.alert(data.message);
            return;
        }
        const option = document.createElement("option");
        option.value = data.data.id;
        option.textContent = `${data.data.name} - ${data.data.phone}`;
        option.selected = true;
        customerSelect.appendChild(option);
        document.getElementById("customer-modal").hidden = true;
    });

    renderItems();
})();
