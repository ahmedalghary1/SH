(function () {
    const form = document.querySelector("[data-purchase-direct-form]");
    if (!form) return;

    function field(id) {
        return document.getElementById(id);
    }

    const productVariant = field("id_product_variant");
    const quantity = field("id_quantity");
    const unitCost = field("id_unit_cost");
    const itemsJson = field("id_items_json");
    const itemsBody = form.querySelector("[data-purchase-items-body]");
    const totalCell = form.querySelector("[data-purchase-total]");
    const discountType = field("id_discount_type");
    const discountValue = field("id_discount_value");
    const addItemButton = form.querySelector("[data-add-purchase-item]");
    let editingIndex = null;
    let items = [];
    try {
        items = itemsJson?.value ? JSON.parse(itemsJson.value || "[]") : [];
    } catch (error) {
        items = [];
    }

    function money(value) {
        return Number(value || 0).toFixed(2);
    }

    function selectedText(select) {
        const option = select?.options[select.selectedIndex];
        return option?.textContent?.trim() || "";
    }

    function updateItemsJson() {
        if (itemsJson) itemsJson.value = JSON.stringify(items);
    }

    function renderItems() {
        if (!itemsBody) return;
        itemsBody.innerHTML = "";
        if (!items.length) {
            itemsBody.innerHTML = '<tr class="empty-row"><td colspan="5">لم تتم إضافة أصناف بعد</td></tr>';
        } else {
            items.forEach((item, index) => {
                const row = document.createElement("tr");
                const lineTotal = Number(item.quantity || 0) * Number(item.unit_cost || 0);
                [item.product_name || "-", item.quantity, money(item.unit_cost), money(lineTotal)].forEach((value) => {
                    const cell = document.createElement("td");
                    cell.textContent = value;
                    row.appendChild(cell);
                });
                const actions = document.createElement("td");
                const editButton = document.createElement("button");
                editButton.className = "btn btn-light btn-small";
                editButton.type = "button";
                editButton.dataset.editPurchaseItem = String(index);
                editButton.textContent = "تعديل";
                actions.appendChild(editButton);
                const removeButton = document.createElement("button");
                removeButton.className = "btn btn-danger btn-small";
                removeButton.type = "button";
                removeButton.dataset.removePurchaseItem = String(index);
                removeButton.disabled = Number(item.received_quantity || 0) > 0;
                removeButton.textContent = removeButton.disabled ? "مستلم" : "حذف";
                actions.appendChild(removeButton);
                row.appendChild(actions);
                itemsBody.appendChild(row);
            });
        }
        if (totalCell) {
            totalCell.textContent = money(items.reduce((sum, item) => (
                sum + (Number(item.quantity || 0) * Number(item.unit_cost || 0))
            ), 0));
        }
        const subtotal = items.reduce((sum, item) => sum + Number(item.quantity || 0) * Number(item.unit_cost || 0), 0);
        const entered = Math.max(0, Number(discountValue?.value || 0));
        const discount = discountType?.value === 'percent' ? subtotal * Math.min(entered, 100) / 100 : Math.min(entered, subtotal);
        form.querySelector('[data-subtotal]').textContent = money(subtotal);
        form.querySelector('[data-discount]').textContent = money(discount);
        form.querySelector('[data-net]').textContent = money(subtotal - discount);
        updateItemsJson();
    }

    discountType?.addEventListener('change', renderItems);
    discountValue?.addEventListener('input', renderItems);

    function requireAny(message, ...inputs) {
        const hasValue = inputs.some((input) => String(input?.value || "").trim());
        if (!hasValue) {
            window.alert(message);
            inputs.find(Boolean)?.focus({ preventScroll: true });
        }
        return hasValue;
    }

    function selectNewOption(select, data) {
        if (!select || !data?.id) return;
        let option = Array.from(select.options).find((candidate) => candidate.value === String(data.id));
        if (!option) {
            option = document.createElement("option");
            option.value = data.id;
            select.appendChild(option);
        }
        option.textContent = data.name;
        option.selected = true;
        select.value = String(data.id);
        select.dispatchEvent(new Event("change", { bubbles: true }));
    }

    function clearFields(...inputs) {
        inputs.forEach((input) => {
            if (!input) return;
            input.value = "";
            input.dispatchEvent(new Event("change", { bubbles: true }));
        });
    }

    function addPurchaseItem() {
        const variantId = productVariant?.value || "";
        const quantityValue = Number(quantity?.value || 0);
        const unitCostValue = Number(unitCost?.value || 0);
        if (!variantId) {
            window.alert("اختر الصنف أولا");
            productVariant?.focus({ preventScroll: true });
            return;
        }
        if (!Number.isInteger(quantityValue) || quantityValue <= 0) {
            window.alert("أدخل كمية صحيحة");
            quantity?.focus({ preventScroll: true });
            return;
        }
        if (!unitCost?.value || !Number.isFinite(unitCostValue) || unitCostValue < 0) {
            window.alert("أدخل سعر شراء صحيح");
            unitCost?.focus({ preventScroll: true });
            return;
        }
        const nextItem = {
            product_variant_id: variantId,
            product_name: selectedText(productVariant),
            quantity: quantityValue,
            unit_cost: unitCostValue,
        };
        if (editingIndex === null) {
            items.push(nextItem);
        } else {
            items[editingIndex] = { ...items[editingIndex], ...nextItem };
            editingIndex = null;
            if (addItemButton) addItemButton.textContent = "إضافة للفاتورة";
        }
        renderItems();
        if (productVariant) productVariant.value = "";
        if (quantity) quantity.value = "1";
        if (unitCost) unitCost.value = "";
    }

    async function postForm(endpoint, payload) {
        const response = await fetch(endpoint, {
            method: "POST",
            headers: { "X-CSRFToken": getCookie("csrftoken") },
            body: payload,
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.message || "تعذر الحفظ");
        }
        return data.data;
    }

    function setLoading(button, isLoading) {
        if (!button) return;
        if (isLoading) {
            button.dataset.originalText = button.textContent;
            button.disabled = true;
            button.textContent = "جار الحفظ...";
        } else {
            button.disabled = false;
            button.textContent = button.dataset.originalText || button.textContent;
        }
    }

    async function saveProduct(button) {
        const productName = field("id_new_product_name");
        const productSku = field("id_new_product_sku");
        const category = field("id_new_category");
        const categoryName = field("id_new_category_name");
        const color = field("id_new_color");
        const colorName = field("id_new_color_name");
        const size = field("id_new_size");
        const sizeName = field("id_new_size_name");

        if (!requireAny("اكتب اسم المنتج الجديد", productName)) return;
        if (!requireAny("اكتب كود المنتج الجديد", productSku)) return;
        if (!requireAny("اختر التصنيف أو اكتب تصنيف جديد", category, categoryName)) return;
        if (!requireAny("اختر اللون أو اكتب لون جديد", color, colorName)) return;
        if (!requireAny("اختر المقاس أو اكتب مقاس جديد", size, sizeName)) return;

        const payload = new FormData();
        [
            "new_product_name",
            "new_product_sku",
            "new_category",
            "new_category_name",
            "new_color",
            "new_color_name",
            "new_size",
            "new_size_name",
            "pieces_per_dozen",
            "retail_price",
            "wholesale_price",
            "unit_cost",
        ].forEach((name) => {
            const input = field(`id_${name}`);
            payload.append(name, input?.value || "");
        });

        setLoading(button, true);
        try {
            const data = await postForm("/purchases/orders/ajax/quick-create-product/", payload);
            selectNewOption(field("id_product_variant"), data);
            if (!data?.offline) {
                clearFields(
                    productName,
                    productSku,
                    category,
                    categoryName,
                    color,
                    colorName,
                    size,
                    sizeName,
                    field("id_pieces_per_dozen"),
                    field("id_retail_price"),
                    field("id_wholesale_price"),
                );
                if (field("id_pieces_per_dozen")) field("id_pieces_per_dozen").value = "12";
            }
            closeModal(button.closest(".modal"));
        } catch (error) {
            window.alert(error.message);
        } finally {
            setLoading(button, false);
        }
    }

    async function saveSupplier(button) {
        const supplierName = field("id_new_supplier_name");
        const supplierPhone = field("id_new_supplier_phone");
        if (!requireAny("اكتب اسم المورد", supplierName)) return;

        const payload = new FormData();
        payload.append("new_supplier_name", supplierName?.value || "");
        payload.append("new_supplier_phone", supplierPhone?.value || "");

        setLoading(button, true);
        try {
            const data = await postForm("/purchases/orders/ajax/quick-create-supplier/", payload);
            selectNewOption(field("id_supplier"), data);
            if (!data?.offline) clearFields(supplierName, supplierPhone);
            closeModal(button.closest(".modal"));
        } catch (error) {
            window.alert(error.message);
        } finally {
            setLoading(button, false);
        }
    }

    form.addEventListener("click", (event) => {
        const addItem = event.target.closest("[data-add-purchase-item]");
        if (addItem) {
            event.preventDefault();
            addPurchaseItem();
            return;
        }

        const removeItem = event.target.closest("[data-remove-purchase-item]");
        if (removeItem) {
            event.preventDefault();
            items.splice(Number(removeItem.dataset.removePurchaseItem), 1);
            renderItems();
            return;
        }

        const editItem = event.target.closest("[data-edit-purchase-item]");
        if (editItem) {
            event.preventDefault();
            editingIndex = Number(editItem.dataset.editPurchaseItem);
            const item = items[editingIndex];
            if (!item) return;
            if (productVariant) productVariant.value = String(item.product_variant_id || item.variant_id || "");
            if (quantity) quantity.value = String(item.quantity || "");
            if (unitCost) unitCost.value = String(item.unit_cost ?? "");
            productVariant?.dispatchEvent(new Event("change", { bubbles: true }));
            if (addItemButton) addItemButton.textContent = "تحديث الصنف";
            productVariant?.focus({ preventScroll: true });
            return;
        }

        const productButton = event.target.closest("[data-complete-quick-product]");
        if (productButton) {
            event.preventDefault();
            saveProduct(productButton);
            return;
        }

        const supplierButton = event.target.closest("[data-complete-quick-supplier]");
        if (supplierButton) {
            event.preventDefault();
            saveSupplier(supplierButton);
        }
    });

    form.addEventListener("submit", () => {
        updateItemsJson();
    });

    renderItems();
})();
