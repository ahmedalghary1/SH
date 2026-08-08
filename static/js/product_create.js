(function () {
    const form = document.querySelector("[data-product-create-form]");
    if (!form) return;

    const config = {
        category: {
            endpoint: "/products/ajax/quick-create-category/",
            selectId: "id_category",
            nameId: "id_new_category_name",
            modalId: "quick-category-modal",
            fields(payload) {
                payload.append("name", document.getElementById(this.nameId)?.value || "");
            },
        },
        color: {
            endpoint: "/products/ajax/quick-create-color/",
            choiceContainerId: "product-color-choices",
            choiceName: "colors",
            nameId: "id_new_color_name",
            modalId: "quick-color-modal",
            fields(payload) {
                payload.append("name", document.getElementById(this.nameId)?.value || "");
                payload.append("hex_code", document.getElementById("quick-color-hex")?.value || "");
            },
        },
        size: {
            endpoint: "/products/ajax/quick-create-size/",
            choiceContainerId: "product-size-choices",
            choiceName: "sizes",
            nameId: "id_new_size_name",
            modalId: "quick-size-modal",
            fields(payload) {
                payload.append("name", document.getElementById(this.nameId)?.value || "");
                payload.append("sort_order", document.getElementById("quick-size-sort-order")?.value || "0");
            },
        },
        warehouse: {
            endpoint: "/products/ajax/quick-create-warehouse/",
            selectId: "id_warehouse",
            nameId: "id_new_warehouse_name",
            modalId: "quick-warehouse-modal",
            fields(payload) {
                payload.append("name", document.getElementById(this.nameId)?.value || "");
                payload.append("warehouse_type", document.getElementById("quick-warehouse-type")?.value || "main");
            },
        },
    };

    async function postQuickCreate(item) {
        const payload = new FormData();
        item.fields(payload);
        const response = await fetch(item.endpoint, {
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

    function selectNewChoice(item, data) {
        const container = document.getElementById(item.choiceContainerId);
        if (!container || !data?.id) return;
        container.querySelector(".choice-empty")?.remove();
        let input = container.querySelector(`input[value="${data.id}"]`);
        if (!input) {
            const label = document.createElement("label");
            label.className = "choice-chip";
            input = document.createElement("input");
            input.type = "checkbox";
            input.name = item.choiceName;
            input.value = data.id;
            input.dataset.label = data.name;
            label.appendChild(input);
            if (data.hex_code) {
                const swatch = document.createElement("i");
                swatch.style.setProperty("--choice-color", data.hex_code);
                label.appendChild(swatch);
            }
            const text = document.createElement("span");
            text.textContent = data.name;
            label.appendChild(text);
            container.appendChild(label);
        }
        input.checked = true;
        input.dispatchEvent(new Event("change", { bubbles: true }));
    }

    form.addEventListener("click", async (event) => {
        const button = event.target.closest("[data-quick-save]");
        if (!button) return;

        const item = config[button.dataset.kind];
        if (!item) return;

        const previousText = button.textContent;
        button.disabled = true;
        button.textContent = "جار الحفظ...";

        try {
            const data = await postQuickCreate(item);
            if (item.choiceContainerId) {
                selectNewChoice(item, data);
            } else {
                selectNewOption(document.getElementById(item.selectId), data);
            }
            const nameInput = document.getElementById(item.nameId);
            if (nameInput && !data?.offline) nameInput.value = "";
            if (typeof closeModal === "function") {
                closeModal(document.getElementById(item.modalId));
            } else {
                document.getElementById(item.modalId).hidden = true;
            }
        } catch (error) {
            window.alert(error.message);
        } finally {
            button.disabled = false;
            button.textContent = previousText;
        }
    });

    const colorChoices = document.getElementById("product-color-choices");
    const sizeChoices = document.getElementById("product-size-choices");
    const quantityRows = document.getElementById("variant-quantity-rows");
    const emptyMessage = document.getElementById("variant-table-empty");
    let initialQuantities = {};
    try {
        initialQuantities = JSON.parse(document.getElementById("initial-variant-quantities")?.textContent || "{}");
    } catch (_) {
        initialQuantities = {};
    }

    function checkedChoices(container) {
        return Array.from(container?.querySelectorAll('input[type="checkbox"]:checked') || []);
    }

    function renderVariantRows() {
        if (!quantityRows) return;
        const currentValues = {};
        quantityRows.querySelectorAll('input[type="number"]').forEach((input) => {
            currentValues[input.dataset.key] = input.value;
        });
        const colors = checkedChoices(colorChoices);
        const sizes = checkedChoices(sizeChoices);
        quantityRows.replaceChildren();

        colors.forEach((color) => {
            sizes.forEach((size) => {
                const key = `${color.value}:${size.value}`;
                const row = document.createElement("tr");
                const colorCell = document.createElement("td");
                const sizeCell = document.createElement("td");
                const quantityCell = document.createElement("td");
                colorCell.textContent = color.dataset.label;
                sizeCell.textContent = size.dataset.label;
                const input = document.createElement("input");
                input.type = "number";
                input.name = `quantity_${color.value}_${size.value}`;
                input.min = "0";
                input.step = "1";
                input.inputMode = "numeric";
                input.dataset.key = key;
                input.value = currentValues[key] ?? initialQuantities[key] ?? "0";
                input.setAttribute("aria-label", `كمية ${color.dataset.label} مقاس ${size.dataset.label}`);
                quantityCell.appendChild(input);
                row.append(colorCell, sizeCell, quantityCell);
                quantityRows.appendChild(row);
            });
        });
        if (emptyMessage) emptyMessage.hidden = colors.length > 0 && sizes.length > 0;
    }

    colorChoices?.addEventListener("change", renderVariantRows);
    sizeChoices?.addEventListener("change", renderVariantRows);
    renderVariantRows();
})();
