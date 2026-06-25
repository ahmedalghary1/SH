(function () {
    const form = document.querySelector("[data-purchase-direct-form]");
    if (!form) return;

    function field(id) {
        return document.getElementById(id);
    }

    function setSelectValue(select, value) {
        if (!select) return;
        select.value = value;
        select.dispatchEvent(new Event("change", { bubbles: true }));
    }

    function requireAny(message, ...inputs) {
        const hasValue = inputs.some((input) => String(input?.value || "").trim());
        if (!hasValue) {
            window.alert(message);
            inputs.find(Boolean)?.focus({ preventScroll: true });
        }
        return hasValue;
    }

    document.addEventListener("click", (event) => {
        const productButton = event.target.closest("[data-complete-quick-product]");
        if (productButton) {
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

            setSelectValue(field("id_product_variant"), "");
            closeModal(productButton.closest(".modal"));
        }

        const supplierButton = event.target.closest("[data-complete-quick-supplier]");
        if (supplierButton) {
            const supplierName = field("id_new_supplier_name");
            if (!requireAny("اكتب اسم المورد الجديد", supplierName)) return;

            setSelectValue(field("id_supplier"), "");
            closeModal(supplierButton.closest(".modal"));
        }
    });
})();
