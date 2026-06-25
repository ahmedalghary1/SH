(function () {
    const form = document.querySelector("[data-purchase-direct-form]");
    if (!form) return;

    function field(id) {
        return document.getElementById(id);
    }

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
            "supplier",
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
            clearFields(supplierName, supplierPhone);
            closeModal(button.closest(".modal"));
        } catch (error) {
            window.alert(error.message);
        } finally {
            setLoading(button, false);
        }
    }

    form.addEventListener("click", (event) => {
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
})();
