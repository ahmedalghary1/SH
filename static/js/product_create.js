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
            selectId: "id_color",
            nameId: "id_new_color_name",
            modalId: "quick-color-modal",
            fields(payload) {
                payload.append("name", document.getElementById(this.nameId)?.value || "");
                payload.append("hex_code", document.getElementById("quick-color-hex")?.value || "");
            },
        },
        size: {
            endpoint: "/products/ajax/quick-create-size/",
            selectId: "id_size",
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
            selectNewOption(document.getElementById(item.selectId), data);
            const nameInput = document.getElementById(item.nameId);
            if (nameInput) nameInput.value = "";
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
})();
