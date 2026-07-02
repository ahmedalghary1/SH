(function () {
    const form = document.querySelector("[data-purchase-return-form]");
    if (!form) return;

    const supplierSelect = document.querySelector("[data-purchase-return-supplier]");
    const variantSelect = document.querySelector("[data-purchase-return-variant]");
    const warehouseSelect = document.querySelector("[data-purchase-return-warehouse]");
    if (!supplierSelect || !variantSelect || !warehouseSelect) return;

    function setOptions(select, items, placeholder, selectedValue = "") {
        select.innerHTML = "";
        const placeholderOption = document.createElement("option");
        placeholderOption.value = "";
        placeholderOption.textContent = placeholder;
        select.appendChild(placeholderOption);

        items.forEach((item) => {
            const option = document.createElement("option");
            option.value = item.id;
            option.textContent = item.label;
            if (item.quantity !== undefined) option.dataset.quantity = item.quantity;
            select.appendChild(option);
        });

        if (selectedValue && Array.from(select.options).some((option) => option.value === String(selectedValue))) {
            select.value = String(selectedValue);
        } else {
            select.value = "";
        }
        select.dispatchEvent(new Event("change", { bubbles: true }));
    }

    function setLoading(select, message) {
        select.disabled = true;
        setOptions(select, [], message);
    }

    async function fetchJson(url) {
        if (!navigator.onLine && window.SHOffline?.handleJsonRequest) {
            const payload = await window.SHOffline.handleJsonRequest(url);
            return payload.data;
        }
        const response = await fetch(url);
        const payload = await response.json();
        if (!response.ok || !payload.success) {
            throw new Error(payload.message || "تعذر تحميل البيانات");
        }
        return payload.data;
    }

    async function loadSupplierVariants() {
        const supplierId = supplierSelect.value;
        setOptions(warehouseSelect, [], "اختر الصنف أولا");
        warehouseSelect.disabled = true;

        if (!supplierId) {
            setOptions(variantSelect, [], "اختر المورد أولا");
            variantSelect.disabled = true;
            return;
        }

        setLoading(variantSelect, "جاري تحميل الأصناف...");
        try {
            const data = await fetchJson(`/purchases/orders/ajax/supplier-product-variants/?supplier_id=${encodeURIComponent(supplierId)}`);
            const variants = (data.variants || []).map((variant) => ({
                id: variant.id,
                label: `${variant.name} - المتاح ${variant.available_quantity}`,
                quantity: variant.available_quantity,
            }));
            variantSelect.disabled = variants.length === 0;
            setOptions(variantSelect, variants, variants.length ? "اختر الصنف" : "لا توجد منتجات متاحة لهذا المورد");
        } catch (error) {
            variantSelect.disabled = true;
            setOptions(variantSelect, [], error.message);
        }
    }

    async function loadVariantWarehouses() {
        const variantId = variantSelect.value;
        if (!variantId) {
            warehouseSelect.disabled = true;
            setOptions(warehouseSelect, [], "اختر الصنف أولا");
            return;
        }

        setLoading(warehouseSelect, "جاري تحميل المخازن...");
        try {
            const data = await fetchJson(`/inventory/ajax/variant-warehouses/?variant_id=${encodeURIComponent(variantId)}&scope=all`);
            const warehouses = (data.warehouses || []).map((warehouse) => ({
                id: warehouse.warehouse_id,
                label: `${warehouse.warehouse_name} - المتاح ${warehouse.quantity}`,
                quantity: warehouse.quantity,
            }));
            warehouseSelect.disabled = warehouses.length === 0;
            setOptions(warehouseSelect, warehouses, warehouses.length ? "اختر المخزن" : "غير متاح في المخازن", warehouses[0]?.id || "");
        } catch (error) {
            warehouseSelect.disabled = true;
            setOptions(warehouseSelect, [], error.message);
        }
    }

    supplierSelect.addEventListener("change", loadSupplierVariants);
    variantSelect.addEventListener("change", loadVariantWarehouses);

    if (!supplierSelect.value) {
        variantSelect.disabled = true;
        warehouseSelect.disabled = true;
        setOptions(variantSelect, [], "اختر المورد أولا");
        setOptions(warehouseSelect, [], "اختر الصنف أولا");
    } else if (!variantSelect.value) {
        loadSupplierVariants();
    } else {
        loadVariantWarehouses();
    }
})();
