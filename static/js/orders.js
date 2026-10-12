(function () {
    const form = document.getElementById("order-form");
    if (!form || form.dataset.orderReady) return;
    form.dataset.orderReady = '1';

    const searchInput = document.getElementById("product-search");
    const variantSelect = document.getElementById("variant-select");
    const itemWarehouse = document.getElementById("item-warehouse");
    const stockInput = document.getElementById("available-stock");
    const priceInput = document.getElementById("unit-price");
    const qtyInput = document.getElementById("item-quantity");
    const unitInput = document.getElementById("item-unit");
    const lineTotalInput = document.getElementById("line-total");
    const addButton = document.getElementById("add-item");
    const body = document.getElementById("order-items-body");
    const itemsJson = document.getElementById("items-json");
    const documentType = document.getElementById("id_document_type");
    const orderType = document.getElementById("id_order_type");
    const warehouse = document.getElementById("id_warehouse");
    const generalDiscount = document.getElementById("id_discount_amount");
    const generalDiscountPercentage = document.getElementById("id_discount_percentage");
    const discountType = document.getElementById("discount-type");
    const customerSelect = document.getElementById("id_customer");
    const customerSearch = document.getElementById("customer-search");
    const customerResults = document.getElementById("customer-results");
    const paymentMethod = document.getElementById("id_payment_method");
    const invoiceKind = document.getElementById("invoice-kind");
    const walletFields = document.querySelectorAll(".wallet-field");
    const walletInputs = [document.getElementById("id_wallet_from_number"), document.getElementById("id_wallet_to_number")];
    const invoiceItemSearch = document.getElementById("invoice-item-search");
    const newInvoiceLink = document.querySelector("[data-new-invoice-link]");
    const newInvoiceSubmit = document.getElementById("new-invoice-submit");
    const initialItemsElement = document.getElementById("initial-order-items");
    const editingOrderId = document.getElementById("editing-order-id")?.value || "";
    const items = initialItemsElement ? JSON.parse(initialItemsElement.textContent || "[]") : [];
    if (warehouse && items.length && !warehouse.value) {
        warehouse.value = items[0].warehouse_id || "";
    }
    let selectedProduct = null;
    let selectedProductLabel = "";
    let productSearchNumber = 0;
    let customerSearchNumber = 0;
    let variantRequestNumber = 0;
    let metaRequestNumber = 0;
    let searchTimer;

    const productCombo = document.createElement("div");
    const productToggle = document.createElement("button");
    const resultsBox = document.createElement("div");
    productCombo.className = "combo-field";
    productToggle.type = "button";
    productToggle.className = "combo-toggle";
    productToggle.setAttribute("aria-label", "فتح قائمة المنتجات");
    resultsBox.id = "product-results";
    resultsBox.className = "combo-list";
    resultsBox.setAttribute("role", "listbox");
    searchInput.parentNode.insertBefore(productCombo, searchInput);
    productCombo.appendChild(searchInput);
    productCombo.appendChild(productToggle);
    productCombo.appendChild(resultsBox);
    searchInput.classList.add("combo-input");
    searchInput.autocomplete = "off";
    searchInput.setAttribute("role", "combobox");
    searchInput.setAttribute("aria-expanded", "false");
    searchInput.setAttribute("aria-haspopup", "listbox");
    if (typeof setupComboAria === 'function') setupComboAria(searchInput, resultsBox);

    function normalizeArabic(value) {
        return String(value || "")
            .trim()
            .toLowerCase()
            .replace(/[\u064b-\u065f\u0670\u0640]/g, "")
            .replace(/[أإآٱ]/g, "ا")
            .replace(/[ىئ]/g, "ي")
            .replace(/ؤ/g, "و")
            .replace(/ة/g, "ه")
            .replace(/ء/g, "")
            .replace(/\s+/g, " ");
    }

    function money(value) {
        return Number(value || 0).toFixed(2);
    }

    function setFieldValue(element, value) {
        if (!element) return;
        if ("value" in element) {
            element.value = value;
        } else {
            element.textContent = value;
        }
    }

    function getFieldValue(element) {
        if (!element) return "";
        return "value" in element ? element.value : element.textContent;
    }

    function setFieldReadOnly(element, readOnly) {
        if (!element) return;
        if ("readOnly" in element) element.readOnly = readOnly;
        element.classList.toggle("is-readonly", Boolean(readOnly));
    }

    function isSample() {
        return documentType?.value === "sample";
    }

    function currentInvoiceKind() {
        if (paymentMethod?.value === "credit") {
            return orderType?.value === "b2b" ? "wholesale_credit" : "retail_credit";
        }
        return orderType?.value === "b2b" ? "wholesale" : "retail";
    }

    function syncInvoiceKindFields() {
        if (!invoiceKind) return;
        if (invoiceKind.value === "wholesale" || invoiceKind.value === "wholesale_credit") {
            if (orderType) orderType.value = "b2b";
        } else if (orderType) {
            orderType.value = "b2c";
        }
        if (paymentMethod) {
            paymentMethod.value = invoiceKind.value.endsWith("_credit") ? "credit" : "cash";
        }
    }

    function syncInvoiceKindFromFields() {
        if (!invoiceKind) return;
        invoiceKind.value = currentInvoiceKind();
        syncInvoiceKindFields();
    }

    function lineDiscount(item) {
        const base = Number(item.unit_price) * Number(item.quantity);
        const amount = Number(item.discount_amount || 0);
        const percentage = Number(item.discount_percentage || 0);
        return Math.min(base, amount + (base * percentage / 100));
    }

    function updateLineTotal() {
        const pieces = getQuantityInPieces();
        if (isSample()) {
            setFieldValue(priceInput, "0.00");
            setFieldReadOnly(priceInput, true);
        } else {
            setFieldReadOnly(priceInput, false);
        }
        setFieldValue(lineTotalInput, money(Number(getFieldValue(priceInput) || 0) * pieces));
    }

    function getSelectedPiecesPerDozen() {
        const selected = variantSelect.options[variantSelect.selectedIndex];
        return Number(selected?.dataset.piecesPerDozen || 12);
    }

    function getQuantityInPieces() {
        const quantity = Number(qtyInput.value || 0);
        if (unitInput?.value === "dozen") {
            return quantity * getSelectedPiecesPerDozen();
        }
        return quantity;
    }

    function toggleWalletFields() {
        const isWallet = paymentMethod?.value === "wallet_transfer" && !isSample() && documentType?.value !== "quote";
        walletFields.forEach((field) => {
            field.hidden = !isWallet;
            field.classList.toggle("is-hidden", !isWallet);
        });
        walletInputs.forEach((input) => {
            if (!input) return;
            input.required = Boolean(isWallet);
            if (!isWallet) input.value = "";
        });
    }

    function updateDocumentMode() {
        const nonPaid = isSample() || documentType?.value === "quote";
        if (paymentMethod) paymentMethod.disabled = nonPaid;
        if (generalDiscount) {
            generalDiscount.disabled = isSample();
            if (isSample()) generalDiscount.value = "0";
        }
        if (generalDiscountPercentage) {
            generalDiscountPercentage.disabled = isSample();
            if (isSample()) generalDiscountPercentage.value = "0";
        }
        updateLineTotal();
        updateSummary();
        toggleWalletFields();
    }

    function updateSummary() {
        const subtotal = items.reduce((sum, item) => sum + (Number(item.unit_price) * Number(item.quantity)), 0);
        const itemDiscount = items.reduce((sum, item) => sum + lineDiscount(item), 0);
        const afterItems = Math.max(subtotal - itemDiscount, 0);
        const discountInput = document.getElementById("discount-input");
        const orderDiscountAmount = isSample() || discountType?.value === "percentage" ? 0 : Number(discountInput?.value || 0);
        const orderDiscountPercentage = isSample() || discountType?.value !== "percentage" ? 0 : Number(discountInput?.value || 0);
        if (generalDiscount) generalDiscount.value = orderDiscountAmount;
        if (generalDiscountPercentage) generalDiscountPercentage.value = orderDiscountPercentage;
        if (discountInput) discountInput.name = discountType?.value === "percentage" ? "" : "discount_amount";
        const orderDiscount = Math.min(afterItems, orderDiscountAmount + (afterItems * orderDiscountPercentage / 100));
        const discount = itemDiscount + orderDiscount;
        const total = Math.max(subtotal - discount, 0);
        document.getElementById("summary-subtotal").textContent = money(subtotal);
        document.getElementById("summary-total").textContent = money(total);
        itemsJson.value = JSON.stringify(items);
    }

    function itemMatchesFilter(item) {
        const q = normalizeArabic(invoiceItemSearch?.value || "");
        if (!q) return true;
        return normalizeArabic([
            item.product_name,
            item.color,
            item.size,
            item.warehouse_name,
        ].join(" ")).includes(q);
    }

    function renderItems() {
        body.innerHTML = "";
        const visibleItems = items.map((item, index) => ({ item, index })).filter(({ item }) => itemMatchesFilter(item));
        if (!items.length) {
            body.innerHTML = '<tr class="empty-row"><td colspan="6">لم تتم إضافة منتجات بعد</td></tr>';
            updateSummary();
            return;
        }
        if (!visibleItems.length) {
            body.innerHTML = '<tr class="empty-row"><td colspan="6">لا توجد أصناف مطابقة للبحث</td></tr>';
            updateSummary();
            return;
        }
        visibleItems.forEach(({ item, index }) => {
            const total = Math.max((Number(item.unit_price) * Number(item.quantity)) - lineDiscount(item), 0);
            const row = document.createElement("tr");
            const nameCell = document.createElement('td');
            nameCell.textContent = item.product_name || '-';
            const variantCell = document.createElement('td');
            variantCell.textContent = `${item.color || '-'} / ${item.size || '-'}`;
            const quantityCell = document.createElement('td');
            const quantityInput = document.createElement('input');
            quantityInput.className = 'invoice-line-input';
            quantityInput.type = 'number';
            quantityInput.min = '1'; quantityInput.step = '1';
            quantityInput.value = Number(item.quantity);
            quantityInput.dataset.lineQuantity = String(index);
            quantityInput.setAttribute('aria-label', `تعديل كمية ${item.product_name || 'الصنف'}`);
            quantityCell.appendChild(quantityInput);
            const priceCell = document.createElement('td');
            const linePrice = document.createElement('input');
            linePrice.className = 'invoice-line-input';
            linePrice.type = 'number'; linePrice.min = '0'; linePrice.step = '0.01';
            linePrice.value = money(item.unit_price);
            linePrice.dataset.linePrice = String(index);
            linePrice.setAttribute('aria-label', `تعديل سعر ${item.product_name || 'الصنف'}`);
            priceCell.appendChild(linePrice);
            const totalCell = document.createElement('td');
            totalCell.textContent = money(total);
            const actions = document.createElement('td');
            const remove = document.createElement('button');
            remove.type = 'button'; remove.className = 'btn btn-danger';
            remove.dataset.remove = String(index); remove.textContent = '✕';
            remove.setAttribute('aria-label', `حذف ${item.product_name || 'الصنف'}`);
            actions.appendChild(remove);
            row.append(nameCell, variantCell, quantityCell, priceCell, totalCell, actions);
            body.appendChild(row);
        });
        updateSummary();
    }

    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== "") {
            const cookies = document.cookie.split(";");
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + "=")) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }

    async function fetchJson(url, options = {}) {
        const headers = {
                'X-CSRFToken': getCookie('csrftoken'),
                ...options.headers,
            };
            if (!(options.body instanceof FormData) && !headers['Content-Type']) {
                headers['Content-Type'] = 'application/json';
            }
        return window.SHHttp.json(url, { ...options, headers });
    }

    function customerLabel(customer) {
        return customer.phone ? `${customer.name} - ${customer.phone}` : customer.name;
    }

    function resetProductMeta() {
        setFieldValue(stockInput, "");
        setFieldValue(priceInput, "");
        itemWarehouse.innerHTML = '<option value="">اختر اللون والمقاس أولا</option>';
        updateLineTotal();
    }

    function openProductResults() {
        if (typeof closeAllCombos === "function") closeAllCombos(productCombo);
        productCombo.classList.add("is-open");
        searchInput.setAttribute("aria-expanded", "true");
    }

    function closeProductResults() {
        productCombo.classList.remove("is-open");
        searchInput.setAttribute("aria-expanded", "false");
    }

    async function renderProductResults(query) {
        const thisSearch = ++productSearchNumber;
        let data;
        try {
            data = await fetchJson(`/orders/ajax/search-products/?q=${encodeURIComponent(query)}`);
        } catch (error) {
            if (thisSearch !== productSearchNumber) return;
            resultsBox.textContent = error.message;
            openProductResults();
            return;
        }
        if (thisSearch !== productSearchNumber) return;
        resultsBox.innerHTML = "";
        if (!data.data.length) {
            const empty = document.createElement("div");
            empty.className = "combo-empty";
            empty.textContent = "لا توجد نتائج";
            resultsBox.appendChild(empty);
            openProductResults();
            return;
        }
        data.data.forEach((product) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "combo-option search-result";
            button.tabIndex = -1;
            button.setAttribute('role', 'option');
            button.textContent = `${product.name} - ${product.sku}`;
            button.dataset.id = product.id;
            button.dataset.name = product.name;
            resultsBox.appendChild(button);
        });
        openProductResults();
    }

    function loadProductResults() {
        renderProductResults(selectedProduct ? "" : searchInput.value.trim());
    }

    searchInput.addEventListener("focus", loadProductResults);
    productToggle.addEventListener("click", () => {
        if (productCombo.classList.contains("is-open")) {
            closeProductResults();
            return;
        }
        searchInput.focus({ preventScroll: true });
        loadProductResults();
    });
    resultsBox.addEventListener("mousedown", (event) => event.preventDefault());

    searchInput.addEventListener("input", async () => {
        const q = searchInput.value.trim();
        if (selectedProduct && searchInput.value !== selectedProductLabel) {
            selectedProduct = null;
            selectedProductLabel = "";
            variantSelect.innerHTML = '<option value="">اختر المنتج أولا</option>';
            resetProductMeta();
        }
        ++productSearchNumber;
        ++variantRequestNumber;
        ++metaRequestNumber;
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => renderProductResults(q), 180);
    });

    resultsBox.addEventListener("click", async (event) => {
        const button = event.target.closest(".search-result");
        if (!button) return;
        selectedProduct = { id: button.dataset.id, name: button.dataset.name };
        const selectedProductId = selectedProduct.id;
        const thisVariantRequest = ++variantRequestNumber;
        ++productSearchNumber;
        clearTimeout(searchTimer);
        searchInput.value = button.textContent;
        selectedProductLabel = button.textContent;
        ++metaRequestNumber;
        closeProductResults();
        resetProductMeta();
        variantSelect.disabled = true;
        variantSelect.innerHTML = '<option value="">جارٍ تحميل الألوان والمقاسات...</option>';
        try {
            const data = await fetchJson(`/orders/ajax/products/${selectedProductId}/variants/`);
            if (thisVariantRequest !== variantRequestNumber || selectedProduct?.id !== selectedProductId) return;
            variantSelect.innerHTML = '<option value="">اختر اللون والمقاس</option>';
            if (data.success && data.data && data.data.length > 0) {
                data.data.forEach((variant) => {
                    const option = document.createElement("option");
                    option.value = variant.id;
                    option.textContent = `${variant.color || "-"} / ${variant.size || "-"} - ${variant.sku}`;
                    option.dataset.color = variant.color;
                    option.dataset.size = variant.size;
                    option.dataset.piecesPerDozen = variant.pieces_per_dozen || 12;
                    variantSelect.appendChild(option);
                });
            } else {
                variantSelect.innerHTML = '<option value="">لا توجد متغيرات لهذا المنتج</option>';
            }
        } catch (error) {
            if (thisVariantRequest !== variantRequestNumber) return;
            console.error('Error fetching variants:', error);
            variantSelect.innerHTML = '<option value="">خطأ في جلب المتغيرات</option>';
        } finally {
            if (thisVariantRequest === variantRequestNumber) variantSelect.disabled = false;
        }
    });

    customerSearch?.addEventListener("input", async () => {
        const thisSearch = ++customerSearchNumber;
        const q = customerSearch.value.trim();
        if (q.length < 1) {
            customerResults.classList.remove("is-open");
            return;
        }
        let data;
        try { data = await fetchJson(`/orders/ajax/search-customers/?q=${encodeURIComponent(q)}`); }
        catch (error) {
            if (thisSearch !== customerSearchNumber) return;
            customerResults.textContent = error.message;
            customerResults.classList.add('is-open');
            return;
        }
        if (thisSearch !== customerSearchNumber) return;
        customerResults.innerHTML = "";
        data.data.forEach((customer) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "search-result";
            button.textContent = customerLabel(customer);
            button.dataset.id = customer.id;
            button.dataset.name = customer.name;
            button.dataset.phone = customer.phone || "";
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
            option.textContent = button.dataset.phone ? `${button.dataset.name} - ${button.dataset.phone}` : button.dataset.name;
            customerSelect.appendChild(option);
        }
        option.selected = true;
        customerSearch.value = option.textContent;
        customerResults.classList.remove("is-open");
        customerSelect.dispatchEvent(new Event('change', { bubbles: true }));
    });

    function updateSelectedWarehouse() {
        const selected = itemWarehouse.options[itemWarehouse.selectedIndex];
        setFieldValue(stockInput, selected?.dataset.quantity || "");
        if (warehouse && itemWarehouse.value) warehouse.value = itemWarehouse.value;
    }

    async function refreshVariantMeta() {
        const thisRequest = ++metaRequestNumber;
        const variantId = variantSelect.value;
        resetProductMeta();
        addButton.disabled = true;
        if (!variantId) return;

        const editingQuery = editingOrderId ? `?editing_order=${encodeURIComponent(editingOrderId)}` : "";
        try {
        const [stock, price] = await Promise.all([
            fetchJson(`/orders/ajax/variants/${variantId}/stock/${editingQuery}`),
            fetchJson(`/orders/ajax/variants/${variantId}/price/?order_type=${encodeURIComponent(orderType?.value || "b2c")}&customer_id=${encodeURIComponent(customerSelect?.value || "")}`),
        ]);
        if (thisRequest !== metaRequestNumber) return;
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
        if (warehouses.length) itemWarehouse.value = warehouses[0].warehouse_id;
        updateSelectedWarehouse();

        setFieldValue(priceInput, isSample() ? "0.00" : price.data.price);
        updateLineTotal();
        addButton.disabled = warehouses.length === 0;
        } catch (error) {
            if (thisRequest !== metaRequestNumber) return;
            if (typeof showPwaNotice === 'function') showPwaNotice(error.message, true);
            else window.alert(error.message);
        }
    }

    variantSelect.addEventListener("change", refreshVariantMeta);
    invoiceKind?.addEventListener("change", () => {
        syncInvoiceKindFields();
        refreshVariantMeta();
        updateSummary();
        toggleWalletFields();
    });
    itemWarehouse.addEventListener("change", () => {
        updateSelectedWarehouse();
        updateLineTotal();
    });
    customerSelect.addEventListener("change", refreshVariantMeta);
    qtyInput.addEventListener("input", updateLineTotal);
    unitInput?.addEventListener("change", updateLineTotal);
    priceInput.addEventListener("input", updateLineTotal);
    document.getElementById("discount-input")?.addEventListener("input", updateSummary);
    discountType?.addEventListener("change", updateSummary);
    generalDiscountPercentage?.addEventListener("input", updateSummary);
    invoiceItemSearch?.addEventListener("input", renderItems);

    addButton.addEventListener("click", () => {
        const selected = variantSelect.options[variantSelect.selectedIndex];
        const selectedWarehouse = itemWarehouse.options[itemWarehouse.selectedIndex];
        const inputQuantity = Number(qtyInput.value || 0);
        const quantity = getQuantityInPieces();
        const available = Number(getFieldValue(stockInput) || 0);
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
        if (!Number.isSafeInteger(quantity) || quantity <= 0 || quantity + alreadySelected > available) {
            window.alert("الكمية غير متاحة");
            return;
        }
        if (!warehouse.value) warehouse.value = itemWarehouse.value;
        const unitPrice = isSample() ? 0 : Number(getFieldValue(priceInput) || 0);
        if (!Number.isFinite(unitPrice) || unitPrice < 0 || !priceInput.checkValidity()) {
            window.alert('أدخل سعرًا صحيحًا.');
            priceInput.focus();
            return;
        }
        items.push({
            variant_id: variantSelect.value,
            product_name: selectedProduct.name,
            color: selected.dataset.color,
            size: selected.dataset.size,
            warehouse_id: itemWarehouse.value,
            warehouse_name: selectedWarehouse?.dataset.name || "",
            available_quantity: available,
            quantity,
            input_quantity: inputQuantity,
            quantity_unit: unitInput?.value || "piece",
            pieces_per_dozen: getSelectedPiecesPerDozen(),
            unit_price: unitPrice,
            discount_amount: 0,
            discount_percentage: 0,
        });
        renderItems();
        form.dataset.unsaved = '1';
        qtyInput.value = 1;
        updateLineTotal();
    });

    body.addEventListener("click", (event) => {
        const remove = event.target.closest("[data-remove]");
        if (!remove) return;
        items.splice(Number(remove.dataset.remove), 1);
        form.dataset.unsaved = '1';
        warehouse.value = items[0]?.warehouse_id || "";
        renderItems();
    });

    body.addEventListener("change", (event) => {
        const quantityInput = event.target.closest("[data-line-quantity]");
        if (quantityInput) {
            const index = Number(quantityInput.dataset.lineQuantity);
            const item = items[index];
            const nextQuantity = Number(quantityInput.value);
            const otherQuantity = items.reduce((sum, candidate, candidateIndex) => {
                if (
                    candidateIndex !== index
                    && candidate.variant_id === item.variant_id
                    && candidate.warehouse_id === item.warehouse_id
                ) {
                    return sum + Number(candidate.quantity || 0);
                }
                return sum;
            }, 0);
            if (!Number.isSafeInteger(nextQuantity) || nextQuantity <= 0 || nextQuantity + otherQuantity > Number(item.available_quantity || 0)) {
                window.alert("الكمية غير متاحة");
                quantityInput.value = item.quantity;
                return;
            }
            item.quantity = nextQuantity;
            item.input_quantity = nextQuantity;
            item.quantity_unit = "piece";
            renderItems();
            return;
        }

        const linePriceInput = event.target.closest("[data-line-price]");
        if (linePriceInput) {
            const index = Number(linePriceInput.dataset.linePrice);
            const nextPrice = Number(linePriceInput.value);
            if (!Number.isFinite(nextPrice) || nextPrice < 0) {
                window.alert("السعر غير صحيح");
                linePriceInput.value = money(items[index].unit_price);
                return;
            }
            items[index].unit_price = nextPrice;
            renderItems();
        }
    });

    newInvoiceLink?.addEventListener("click", (event) => {
        if (!items.length || !newInvoiceSubmit) return;
        event.preventDefault();
        if (typeof form.requestSubmit === "function") {
            form.requestSubmit(newInvoiceSubmit);
        } else {
            newInvoiceSubmit.click();
        }
    });

    form.addEventListener("click", (event) => {
        const deleteDraft = event.target.closest("[data-delete-draft]");
        if (!deleteDraft) return;
        if (!window.confirm("هل تريد حذف الفاتورة المعلقة؟")) {
            event.preventDefault();
            return;
        }
        form.dataset.submitIntent = "delete-draft";
    });

    form.addEventListener("submit", (event) => {
        const submitter = event.submitter;
        if (form.dataset.submitIntent === "delete-draft" || submitter?.matches("[data-delete-draft]")) {
            delete form.dataset.submitIntent;
            return;
        }
        syncInvoiceKindFields();
        if (!items.length) {
            event.preventDefault();
            window.alert("أضف منتجا واحدا على الأقل");
            return;
        }
        if (!warehouse.value) {
            event.preventDefault();
            window.alert("اختر مخزنا من بيانات المنتج قبل حفظ الفاتورة");
        }
    });

    document.getElementById("quick-customer-save")?.addEventListener("click", async (event) => {
        const button = event.currentTarget;
        const previousText = button.textContent;
        button.disabled = true;
        button.textContent = 'جارٍ الحفظ...';
        try {
        const payload = new FormData();
        payload.append("name", document.getElementById("quick-customer-name").value);
        payload.append("customer_type", document.getElementById("quick-customer-type").value);
        payload.append("phone", document.getElementById("quick-customer-phone").value);
        payload.append("address", document.getElementById("quick-customer-address").value);
        const quickCustomerSalesRep = document.getElementById("quick-customer-sales-representative");
        if (quickCustomerSalesRep) {
            payload.append("sales_representative", quickCustomerSalesRep.value);
        }
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
        option.textContent = customerLabel(data.data);
        option.selected = true;
        customerSelect.appendChild(option);
        customerSelect.dispatchEvent(new Event('change', { bubbles: true }));
        if (typeof closeModal === "function") {
            closeModal(document.getElementById("customer-modal"));
        } else {
            document.getElementById("customer-modal").hidden = true;
        }
        } catch (error) {
            window.alert(error.message);
        } finally {
            button.disabled = false;
            button.textContent = previousText;
        }
    });

    syncInvoiceKindFromFields();
    renderItems();
    updateDocumentMode();
    updateLineTotal();

})();
