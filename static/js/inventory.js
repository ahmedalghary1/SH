(function () {
    // Stock Filter Functionality
    function setupStockWarehouseFilters(root = document) {
        root.querySelectorAll("[data-stock-filter-target]").forEach((variantSelect) => {
            if (variantSelect.dataset.stockFilterReady) return;
            const warehouseSelect = document.getElementById(variantSelect.dataset.stockFilterTarget);
            if (!warehouseSelect) return;
            variantSelect.dataset.stockFilterReady = "true";
            const initialPlaceholder = warehouseSelect.options[0]?.textContent || "اختر المخزن";
            const scope = variantSelect.dataset.stockFilterScope || "all";

            async function updateWarehouses() {
                const variantId = variantSelect.value;
                const selectedValue = warehouseSelect.value;
                if (!variantId) {
                    warehouseSelect.disabled = true;
                    setWarehouseOptions(warehouseSelect, [], "اختر المنتج أولا");
                    return;
                }
                warehouseSelect.disabled = true;
                setWarehouseOptions(warehouseSelect, [], "جاري تحميل المخازن...");
                try {
                    const response = await fetch(`/inventory/ajax/variant-warehouses/?variant_id=${encodeURIComponent(variantId)}&scope=${encodeURIComponent(scope)}`);
                    const payload = await response.json();
                    const warehouses = payload.data?.warehouses || [];
                    warehouseSelect.disabled = warehouses.length === 0;
                    setWarehouseOptions(
                        warehouseSelect,
                        warehouses,
                        warehouses.length ? initialPlaceholder : "غير متاح في المخازن",
                        selectedValue,
                    );
                } catch (error) {
                    warehouseSelect.disabled = true;
                    setWarehouseOptions(warehouseSelect, [], "تعذر تحميل المخازن");
                }
            }

            variantSelect.addEventListener("change", updateWarehouses);
            updateWarehouses();
        });
    }

    function setWarehouseOptions(select, warehouses, placeholder, selectedValue = "") {
        select.innerHTML = "";
        const placeholderOption = document.createElement("option");
        placeholderOption.value = "";
        placeholderOption.textContent = placeholder;
        select.appendChild(placeholderOption);
        warehouses.forEach((warehouse) => {
            const option = document.createElement("option");
            option.value = warehouse.warehouse_id;
            option.textContent = `${warehouse.warehouse_name} - المتاح ${warehouse.quantity}`;
            option.dataset.quantity = warehouse.quantity;
            select.appendChild(option);
        });
        if (selectedValue && Array.from(select.options).some((option) => option.value === selectedValue)) {
            select.value = selectedValue;
        } else {
            select.value = "";
        }
        select.dispatchEvent(new Event("change", { bubbles: true }));
    }

    document.addEventListener("DOMContentLoaded", () => {
        setupStockWarehouseFilters();
    });
})();
