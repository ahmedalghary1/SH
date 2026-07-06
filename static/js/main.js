function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== "") {
        const cookies = document.cookie.split(";");
        for (let i = 0; i < cookies.length; i += 1) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === `${name}=`) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

const isAuthPage = window.location.pathname.startsWith("/accounts/");

if ("serviceWorker" in navigator && isAuthPage) {
    navigator.serviceWorker.getRegistrations?.()
        .then((registrations) => Promise.all(registrations.map((registration) => registration.unregister())))
        .catch((error) => {
            console.warn("Service worker unregister failed on auth page", error);
        });
}

if ("serviceWorker" in navigator && !isAuthPage) {
    window.addEventListener("load", () => {
        navigator.serviceWorker.register("/service-worker.js", { scope: "/" })
            .then((registration) => registration.update?.())
            .catch((error) => {
                console.warn("Service worker registration failed", error);
            });
    });
}

function showPwaNotice(message, isError = false) {
    let notice = document.querySelector("[data-pwa-notice]");
    if (!notice) {
        notice = document.createElement("div");
        notice.dataset.pwaNotice = "true";
        notice.style.position = "fixed";
        notice.style.insetInlineStart = "18px";
        notice.style.bottom = "18px";
        notice.style.zIndex = "2200";
        notice.style.maxWidth = "360px";
        notice.style.padding = "12px 14px";
        notice.style.borderRadius = "8px";
        notice.style.boxShadow = "0 8px 24px rgba(0,0,0,.16)";
        notice.style.fontWeight = "600";
        document.body.appendChild(notice);
    }
    notice.textContent = message;
    notice.style.background = isError ? "#8b1e2d" : "#123c69";
    notice.style.color = "#fff";
    notice.hidden = false;
    window.clearTimeout(showPwaNotice.timer);
    showPwaNotice.timer = window.setTimeout(() => {
        notice.hidden = true;
    }, 5200);
}

window.addEventListener("DOMContentLoaded", () => {
    const url = new URL(window.location.href);
    if (url.searchParams.get("offline_saved") !== "1") return;
    showPwaNotice("\u062a\u0645 \u0627\u0644\u062d\u0641\u0638 \u0645\u062d\u0644\u064a\u0627. \u0633\u062a\u062a\u0645 \u0627\u0644\u0645\u0632\u0627\u0645\u0646\u0629 \u062a\u0644\u0642\u0627\u0626\u064a\u0627 \u0639\u0646\u062f \u0639\u0648\u062f\u0629 \u0627\u0644\u0627\u062a\u0635\u0627\u0644.");
    url.searchParams.delete("offline_saved");
    window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
});

let deferredPwaInstallPrompt = null;

window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferredPwaInstallPrompt = event;
    document.querySelectorAll("[data-pwa-install]").forEach((button) => {
        button.hidden = false;
    });
});

window.addEventListener("appinstalled", () => {
    deferredPwaInstallPrompt = null;
    document.querySelectorAll("[data-pwa-install]").forEach((button) => {
        button.hidden = true;
    });
    window.SHSync?.cacheAppShell?.();
    window.SHSync?.bootstrapNow?.();
});

document.addEventListener("submit", (event) => {
    const form = event.target;
    const message = form.getAttribute("data-confirm");
    if (message && !window.confirm(message)) {
        event.preventDefault();
        return;
    }
    const missingCombo = Array.from(
        form.querySelectorAll(".combo-source[data-original-required='true']:not(:disabled)")
    ).find((select) => !select.value);
    if (missingCombo) {
        const combo = missingCombo.closest(".combo-field");
        const input = combo?.querySelector(".combo-input");
        event.preventDefault();
        input?.setCustomValidity("اختر قيمة من القائمة");
        input?.focus({ preventScroll: true });
        input?.reportValidity();
    }
});

function openModal(modal) {
    if (!modal) return;
    modal.hidden = false;
    document.body.classList.add("modal-open");
    const firstField = modal.querySelector("input, select, textarea, button, a[href]");
    firstField?.focus({ preventScroll: true });
}

function closeModal(modal) {
    if (!modal) return;
    modal.hidden = true;
    if (!document.querySelector(".modal:not([hidden])")) {
        document.body.classList.remove("modal-open");
    }
}

function getComboText(value, fallback = "") {
    return String(value || fallback || "").trim();
}

function normalizeSearchText(value) {
    return getComboText(value)
        .toLowerCase()
        .replace(/[\u064b-\u065f\u0670\u0640]/g, "")
        .replace(/[أإآٱ]/g, "ا")
        .replace(/[ىئ]/g, "ي")
        .replace(/ؤ/g, "و")
        .replace(/ة/g, "ه")
        .replace(/ء/g, "")
        .replace(/\s+/g, " ");
}

function closeCombo(combo) {
    if (!combo) return;
    combo.classList.remove("is-open");
    const input = combo.querySelector(".combo-input");
    input?.setAttribute("aria-expanded", "false");
}

function closeAllCombos(except = null) {
    document.querySelectorAll(".combo-field.is-open").forEach((combo) => {
        if (combo !== except) closeCombo(combo);
    });
}

function buildComboOption(label, value, isSelected = false) {
    const option = document.createElement("button");
    option.type = "button";
    option.className = "combo-option";
    option.textContent = label || value || "-";
    option.dataset.value = value;
    option.setAttribute("role", "option");
    option.setAttribute("aria-selected", String(isSelected));
    return option;
}

function enhanceSelect(select) {
    if (select.dataset.comboReady || select.multiple || select.closest(".combo-field")) return;
    if (select.hidden || select.disabled && select.options.length <= 1) return;

    select.dataset.comboReady = "true";
    select.dataset.originalRequired = String(select.required);
    select.required = false;
    const combo = document.createElement("div");
    combo.className = "combo-field";
    const input = document.createElement("input");
    input.type = "text";
    input.className = "combo-input";
    input.autocomplete = "off";
    input.disabled = select.disabled;
    input.required = select.dataset.originalRequired === "true";
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-expanded", "false");
    input.setAttribute("aria-haspopup", "listbox");

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "combo-toggle";
    toggle.disabled = select.disabled;
    toggle.setAttribute("aria-label", "افتح القائمة");

    const list = document.createElement("div");
    list.className = "combo-list";
    list.setAttribute("role", "listbox");

    select.parentNode.insertBefore(combo, select);
    combo.appendChild(select);
    combo.appendChild(input);
    combo.appendChild(toggle);
    combo.appendChild(list);
    select.classList.add("combo-source");
    select.tabIndex = -1;

    function optionData() {
        return Array.from(select.options).map((option) => ({
            value: option.value,
            label: getComboText(option.textContent, option.value),
            disabled: option.disabled,
            selected: option.selected,
        }));
    }

    function selectedOption() {
        return select.options[select.selectedIndex] || null;
    }

    function syncInput() {
        const selected = selectedOption();
        const label = selected ? getComboText(selected.textContent, selected.value) : "";
        input.value = selected && selected.value ? label : "";
        input.title = selected && selected.value ? label : "";
        input.placeholder = selected && !selected.value ? label : "";
        input.disabled = select.disabled;
        input.required = select.dataset.originalRequired === "true" && !select.disabled;
        toggle.disabled = select.disabled;
        combo.classList.toggle("is-disabled", select.disabled);
    }

    function render(term = input.value) {
        const query = normalizeSearchText(term);
        const options = optionData().filter((option) => {
            return !query || normalizeSearchText(option.label).includes(query) || normalizeSearchText(option.value).includes(query);
        });
        list.innerHTML = "";
        options.forEach((option) => {
            const button = buildComboOption(option.label, option.value, option.selected);
            button.disabled = option.disabled;
            list.appendChild(button);
        });
        if (!options.length) {
            const empty = document.createElement("div");
            empty.className = "combo-empty";
            empty.textContent = "لا توجد نتائج";
            list.appendChild(empty);
        }
    }

    function openCombo(term = "") {
        if (select.disabled) return;
        closeAllCombos(combo);
        render(term);
        combo.classList.add("is-open");
        input.setAttribute("aria-expanded", "true");
    }

    function setSelectValue(value, shouldDispatch = true) {
        if (select.value !== value) {
            select.value = value;
            if (shouldDispatch) {
                select.dispatchEvent(new Event("change", { bubbles: true }));
            }
        }
        syncInput();
    }

    input.addEventListener("focus", () => openCombo(""));
    input.addEventListener("input", () => {
        input.setCustomValidity("");
        const typed = getComboText(input.value);
        const typedLower = normalizeSearchText(typed);
        const exact = optionData().find((option) => !option.disabled && normalizeSearchText(option.label) === typedLower);
        if (exact) {
            setSelectValue(exact.value);
        } else if (select.value) {
            setSelectValue("");
        }
        openCombo(typed);
    });

    toggle.addEventListener("click", () => {
        if (combo.classList.contains("is-open")) {
            closeCombo(combo);
            return;
        }
        input.focus({ preventScroll: true });
        openCombo("");
    });

    list.addEventListener("mousedown", (event) => {
        event.preventDefault();
    });

    list.addEventListener("click", (event) => {
        const option = event.target.closest(".combo-option");
        if (!option || option.disabled) return;
        input.setCustomValidity("");
        setSelectValue(option.dataset.value);
        closeCombo(combo);
    });

    select.addEventListener("change", () => {
        syncInput();
        if (combo.classList.contains("is-open")) render();
    });

    new MutationObserver(() => {
        syncInput();
        if (combo.classList.contains("is-open")) render();
    }).observe(select, { childList: true, subtree: true, attributes: true, attributeFilter: ["disabled", "required", "selected"] });

    syncInput();
}

function enhanceListInput(input) {
    if (input.dataset.comboReady || input.closest(".combo-field")) return;
    const datalist = document.getElementById(input.getAttribute("list"));
    if (!datalist) return;

    input.dataset.comboReady = "true";
    input.dataset.originalList = input.getAttribute("list");
    input.removeAttribute("list");
    input.classList.add("combo-input");
    input.autocomplete = "off";
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-expanded", "false");
    input.setAttribute("aria-haspopup", "listbox");

    const combo = document.createElement("div");
    combo.className = "combo-field";
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "combo-toggle";
    toggle.setAttribute("aria-label", "افتح القائمة");
    const list = document.createElement("div");
    list.className = "combo-list";
    list.setAttribute("role", "listbox");

    input.parentNode.insertBefore(combo, input);
    combo.appendChild(input);
    combo.appendChild(toggle);
    combo.appendChild(list);

    function datalistOptions() {
        return Array.from(datalist.options).map((option) => ({
            value: option.value,
            label: getComboText(option.label, option.value),
        }));
    }

    function render(term = input.value) {
        const query = normalizeSearchText(term);
        const options = datalistOptions().filter((option) => {
            return !query || normalizeSearchText(option.label).includes(query) || normalizeSearchText(option.value).includes(query);
        });
        list.innerHTML = "";
        options.forEach((option) => {
            list.appendChild(buildComboOption(option.label, option.value, option.value === input.value));
        });
        if (!options.length) {
            const empty = document.createElement("div");
            empty.className = "combo-empty";
            empty.textContent = "لا توجد نتائج";
            list.appendChild(empty);
        }
    }

    function openCombo(term = "") {
        if (input.disabled) return;
        closeAllCombos(combo);
        render(term);
        combo.classList.add("is-open");
        input.setAttribute("aria-expanded", "true");
    }

    input.addEventListener("focus", () => openCombo(""));
    input.addEventListener("input", () => openCombo(input.value));
    toggle.addEventListener("click", () => {
        if (combo.classList.contains("is-open")) {
            closeCombo(combo);
            return;
        }
        input.focus({ preventScroll: true });
        openCombo("");
    });
    list.addEventListener("mousedown", (event) => {
        event.preventDefault();
    });
    list.addEventListener("click", (event) => {
        const option = event.target.closest(".combo-option");
        if (!option) return;
        input.value = option.dataset.value;
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
        closeCombo(combo);
    });

    new MutationObserver(() => {
        if (combo.classList.contains("is-open")) render();
    }).observe(datalist, { childList: true, subtree: true, attributes: true });
}

function enhanceListControls(root = document) {
    root.querySelectorAll("select:not([data-native-select])").forEach(enhanceSelect);
    root.querySelectorAll("input[list]:not([data-native-list])").forEach(enhanceListInput);
}

function setupPasswordToggles(root = document) {
    root.querySelectorAll('input[type="password"]:not([data-password-toggle-ready])').forEach((input) => {
        input.dataset.passwordToggleReady = "true";
        const wrapper = document.createElement("span");
        wrapper.className = "password-field";
        input.parentNode.insertBefore(wrapper, input);
        wrapper.appendChild(input);

        const button = document.createElement("button");
        button.type = "button";
        button.className = "password-toggle";
        button.setAttribute("aria-label", "إظهار كلمة المرور");
        button.setAttribute("title", "إظهار كلمة المرور");
        button.textContent = "👁";
        wrapper.appendChild(button);

        button.addEventListener("click", () => {
            const isHidden = input.type === "password";
            input.type = isHidden ? "text" : "password";
            button.setAttribute("aria-label", isHidden ? "إخفاء كلمة المرور" : "إظهار كلمة المرور");
            button.setAttribute("title", isHidden ? "إخفاء كلمة المرور" : "إظهار كلمة المرور");
            input.focus({ preventScroll: true });
        });
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
                const offlinePayload = await window.SHOffline?.handleJsonRequest?.(`/inventory/ajax/variant-warehouses/?variant_id=${encodeURIComponent(variantId)}&scope=${encodeURIComponent(scope)}`).catch(() => null);
                if (offlinePayload?.success) {
                    const warehouses = offlinePayload.data?.warehouses || [];
                    warehouseSelect.disabled = warehouses.length === 0;
                    setWarehouseOptions(warehouseSelect, warehouses, warehouses.length ? initialPlaceholder : "Offline stock", selectedValue);
                    return;
                }
                warehouseSelect.disabled = true;
                setWarehouseOptions(warehouseSelect, [], "تعذر تحميل المخازن");
            }
        }

        variantSelect.addEventListener("change", updateWarehouses);
        updateWarehouses();
    });
}

document.addEventListener("click", (event) => {
    const historyToggle = event.target.closest("[data-audit-history-toggle]");
    if (historyToggle) {
        const widget = historyToggle.closest(".audit-history-widget");
        const panel = widget?.querySelector("[data-audit-history-panel]");
        if (panel) {
            const isOpen = panel.hidden;
            panel.hidden = !isOpen;
            historyToggle.setAttribute("aria-expanded", String(isOpen));
        }
    }

    if (!event.target.closest(".combo-field")) {
        closeAllCombos();
    }

    const opener = event.target.closest("[data-open-modal]");
    if (opener) {
        openModal(document.getElementById(opener.dataset.openModal));
    }

    const closeButton = event.target.closest("[data-close-modal]");
    if (closeButton) {
        closeModal(closeButton.closest(".modal"));
    }

    const installButton = event.target.closest("[data-pwa-install]");
    if (installButton && deferredPwaInstallPrompt) {
        deferredPwaInstallPrompt.prompt();
        deferredPwaInstallPrompt.userChoice.finally(() => {
            deferredPwaInstallPrompt = null;
            installButton.hidden = true;
        });
    }

    const syncButton = event.target.closest("[data-pwa-sync]");
    if (syncButton) {
        syncButton.disabled = true;
        Promise.resolve()
            .then(() => window.SHSync?.cacheAppShell?.())
            .then(() => window.SHSync?.bootstrapNow?.())
            .then(() => window.SHSync?.processQueue?.())
            .finally(() => {
                syncButton.disabled = false;
            });
    }

});

document.addEventListener("DOMContentLoaded", () => {
    enhanceListControls();
    setupPasswordToggles();
    setupStockWarehouseFilters();

    const currentPath = window.location.pathname;
    document.querySelectorAll(".side-nav a").forEach((link) => {
        const linkPath = new URL(link.href, window.location.origin).pathname;
        if (linkPath === currentPath || (linkPath !== "/" && currentPath.startsWith(linkPath))) {
            link.classList.add("is-active");
            const group = link.closest(".nav-group");
            if (group) {
                group.classList.add("is-open", "is-active");
                group.querySelector(".nav-group-toggle")?.setAttribute("aria-expanded", "true");
            }
        }
    });

    const hasOpenGroup = document.querySelector(".nav-group.is-open");
    if (!hasOpenGroup) {
        const firstGroup = document.querySelector(".nav-group");
        firstGroup?.classList.add("is-open");
        firstGroup?.querySelector(".nav-group-toggle")?.setAttribute("aria-expanded", "true");
    }
});

document.addEventListener("click", (event) => {
    const groupToggle = event.target.closest("[data-nav-group-toggle]");
    if (groupToggle) {
        event.preventDefault();
        event.stopPropagation();
        const group = groupToggle.closest(".nav-group");
        if (!group) return;
        const isOpen = !group.classList.contains("is-open");
        group.classList.toggle("is-open", isOpen);
        groupToggle.setAttribute("aria-expanded", String(isOpen));
        return;
    }

    if (event.target.closest("[data-sidebar-toggle]")) {
        document.body.classList.toggle("sidebar-open");
    }

    if (event.target.closest("[data-sidebar-close]") || event.target.closest(".side-nav a")) {
        document.body.classList.remove("sidebar-open");
    }
});

document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    closeAllCombos();
    document.body.classList.remove("sidebar-open");
});

// Advanced Options Toggle
document.addEventListener("click", (event) => {
    const advancedToggle = event.target.closest("[data-advanced-toggle]");
    if (advancedToggle) {
        event.preventDefault();
        const advancedPanel = advancedToggle.nextElementSibling;
        if (!advancedPanel || !advancedPanel.hasAttribute("data-advanced-panel")) return;

        const isExpanded = advancedToggle.getAttribute("aria-expanded") === "true";
        advancedToggle.setAttribute("aria-expanded", !isExpanded);
        advancedPanel.setAttribute("aria-hidden", isExpanded);
    }
});
