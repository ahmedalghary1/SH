(function () {
    const form = document.getElementById("order-form");
    if (!form) return;

    const searchInput = document.getElementById("product-search");
    const resultsBox = document.getElementById("product-results");
    const variantSelect = document.getElementById("variant-select");
    const itemWarehouse = document.getElementById("item-warehouse");
    const stockInput = document.getElementById("available-stock");
    const priceInput = document.getElementById("unit-price");
    const qtyInput = document.getElementById("item-quantity");
    const lineTotalInput = document.getElementById("line-total");
    const addButton = document.getElementById("add-item");
    const body = document.getElementById("order-items-body");
    const itemsJson = document.getElementById("items-json");
    const orderType = document.getElementById("id_order_type");
    const warehouse = document.getElementById("id_warehouse");
    const generalDiscount = document.getElementById("id_discount_amount");
    const generalDiscountPercentage = document.getElementById("id_discount_percentage");
    const customerSelect = document.getElementById("id_customer");
    const customerSearch = document.getElementById("customer-search");
    const customerResults = document.getElementById("customer-results");
    const paymentMethod = document.getElementById("id_payment_method");
    const walletFields = document.querySelectorAll(".wallet-field");
    const walletInputs = [document.getElementById("id_wallet_from_number"), document.getElementById("id_wallet_to_number")];
    const items = [];
    let selectedProduct = null;

    function money(value) {
        return Number(value || 0).toFixed(2);
    }

    function lineDiscount(item) {
        const base = Number(item.unit_price) * Number(item.quantity);
        const amount = Number(item.discount_amount || 0);
        const percentage = Number(item.discount_percentage || 0);
        return Math.min(base, amount + (base * percentage / 100));
    }

    function updateLineTotal() {
        if (!lineTotalInput) return;
        lineTotalInput.value = money(Number(priceInput.value || 0) * Number(qtyInput.value || 0));
    }

    function toggleWalletFields() {
        const isWallet = paymentMethod?.value === "wallet_transfer";
        walletFields.forEach((field) => {
            field.hidden = !isWallet;
        });
        walletInputs.forEach((input) => {
            if (!input) return;
            input.required = Boolean(isWallet);
            if (!isWallet) input.value = "";
        });
    }

    function updateSummary() {
        const subtotal = items.reduce((sum, item) => sum + (Number(item.unit_price) * Number(item.quantity)), 0);
        const itemDiscount = items.reduce((sum, item) => sum + lineDiscount(item), 0);
        const afterItems = Math.max(subtotal - itemDiscount, 0);
        const orderDiscountAmount = generalDiscount ? Number(generalDiscount.value || 0) : 0;
        const orderDiscountPercent = generalDiscountPercentage ? Number(generalDiscountPercentage.value || 0) : 0;
        const orderDiscount = Math.min(afterItems, orderDiscountAmount + (afterItems * orderDiscountPercent / 100));
        const discount = itemDiscount + orderDiscount;
        const total = Math.max(subtotal - discount, 0);
        document.getElementById("summary-subtotal").textContent = money(subtotal);
        document.getElementById("summary-discount").textContent = money(discount);
        document.getElementById("summary-total").textContent = money(total);
        const paidNode = document.getElementById("summary-paid");
        const remainingNode = document.getElementById("summary-remaining");
        if (paidNode) paidNode.textContent = money(total);
        if (remainingNode) remainingNode.textContent = money(0);
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
            const total = Math.max((Number(item.unit_price) * Number(item.quantity)) - lineDiscount(item), 0);
            const row = document.createElement("tr");
            row.innerHTML = `
                <td>${item.product_name}</td>
                <td>${item.color || "-"}</td>
                <td>${item.size || "-"}</td>
                <td>${item.warehouse_name || "-"}</td>
                <td>${item.quantity}</td>
                <td>${money(item.unit_price)}</td>
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

    function resetProductMeta() {
        stockInput.value = "";
        priceInput.value = "";
        itemWarehouse.innerHTML = '<option value="">اختر اللون والمقاس أولا</option>';
        updateLineTotal();
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
        resetProductMeta();
        const data = await fetchJson(`/orders/ajax/products/${selectedProduct.id}/variants/`);
        variantSelect.innerHTML = '<option value="">اختر اللون والمقاس</option>';
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
        refreshVariantMeta();
    });

    function updateSelectedWarehouse() {
        const selected = itemWarehouse.options[itemWarehouse.selectedIndex];
        stockInput.value = selected?.dataset.quantity || "";
        if (warehouse && itemWarehouse.value) {
            warehouse.value = itemWarehouse.value;
        }
    }

    async function refreshVariantMeta() {
        const variantId = variantSelect.value;
        resetProductMeta();
        if (!variantId) return;

        const stock = await fetchJson(`/orders/ajax/variants/${variantId}/stock/`);
        const warehouses = stock.data.warehouses || [];
        itemWarehouse.innerHTML = warehouses.length
            ? '<option value="">اختر المخزن</option>'
            : '<option value="">غير متاح في المخزون</option>';
        warehouses.forEach((warehouseStock) => {
            const option = document.createElement("option");
            option.value = warehouseStock.warehouse_id;
            option.textContent = `${warehouseStock.warehouse_name} - المتاح ${warehouseStock.quantity}`;
            option.dataset.quantity = warehouseStock.quantity;
            option.dataset.name = warehouseStock.warehouse_name;
            itemWarehouse.appendChild(option);
        });
        if (warehouses.length) {
            itemWarehouse.value = warehouses[0].warehouse_id;
        }
        updateSelectedWarehouse();

        const price = await fetchJson(`/orders/ajax/variants/${variantId}/price/?order_type=${orderType.value}&customer_id=${customerSelect.value || ""}`);
        priceInput.value = price.data.price;
        updateLineTotal();
    }

    variantSelect.addEventListener("change", refreshVariantMeta);
    itemWarehouse.addEventListener("change", () => {
        updateSelectedWarehouse();
        updateLineTotal();
    });
    orderType.addEventListener("change", refreshVariantMeta);
    customerSelect.addEventListener("change", refreshVariantMeta);
    paymentMethod?.addEventListener("change", toggleWalletFields);
    qtyInput.addEventListener("input", updateLineTotal);
    generalDiscount?.addEventListener("input", updateSummary);
    generalDiscountPercentage?.addEventListener("input", updateSummary);

    addButton.addEventListener("click", () => {
        const selected = variantSelect.options[variantSelect.selectedIndex];
        const selectedWarehouse = itemWarehouse.options[itemWarehouse.selectedIndex];
        const quantity = Number(qtyInput.value || 0);
        const available = Number(stockInput.value || 0);
        if (!selectedProduct || !variantSelect.value) {
            window.alert("اختر المنتج واللون والمقاس أولا");
            return;
        }
        if (!itemWarehouse.value) {
            window.alert("اختر المخزن المتاح لهذا المنتج");
            return;
        }
        const alreadySelected = items
            .filter((item) => item.variant_id === variantSelect.value && item.warehouse_id === itemWarehouse.value)
            .reduce((sum, item) => sum + Number(item.quantity || 0), 0);
        if (quantity <= 0 || quantity + alreadySelected > available) {
            window.alert("الكمية غير متاحة");
            return;
        }
        if (!warehouse.value) warehouse.value = itemWarehouse.value;
        items.push({
            variant_id: variantSelect.value,
            product_name: selectedProduct.name,
            color: selected.dataset.color,
            size: selected.dataset.size,
            warehouse_id: itemWarehouse.value,
            warehouse_name: selectedWarehouse?.dataset.name || "",
            quantity,
            unit_price: Number(priceInput.value || 0),
            discount_amount: 0,
            discount_percentage: 0,
        });
        renderItems();
        qtyInput.value = 1;
        updateLineTotal();
    });

    body.addEventListener("click", (event) => {
        const remove = event.target.closest("[data-remove]");
        if (!remove) return;
        items.splice(Number(remove.dataset.remove), 1);
        warehouse.value = items[0]?.warehouse_id || "";
        renderItems();
    });

    form.addEventListener("submit", (event) => {
        if (!items.length) {
            event.preventDefault();
            window.alert("أضف منتجا واحدا على الأقل");
            return;
        }
        if (!warehouse.value) {
            event.preventDefault();
            window.alert("اختر مخزنا من بيانات المنتج قبل تأكيد الفاتورة");
        }
    });

    document.getElementById("quick-customer-save")?.addEventListener("click", async () => {
        const payload = new FormData();
        payload.append("name", document.getElementById("quick-customer-name").value);
        payload.append("customer_type", document.getElementById("quick-customer-type").value);
        payload.append("phone", document.getElementById("quick-customer-phone").value);
        payload.append("address", document.getElementById("quick-customer-address").value);
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
        if (typeof closeModal === "function") {
            closeModal(document.getElementById("customer-modal"));
        } else {
            document.getElementById("customer-modal").hidden = true;
        }
        refreshVariantMeta();
    });

    renderItems();
    toggleWalletFields();
    updateLineTotal();
})();
