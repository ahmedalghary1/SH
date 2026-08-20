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

function localDateTimeParts(date = new Date()) {
    const pad = (value) => String(value).padStart(2, "0");
    return {
        display: `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`,
        input: `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`,
    };
}

function updateLiveDateTime() {
    const value = localDateTimeParts();
    document.querySelectorAll("[data-live-datetime]").forEach((node) => {
        node.textContent = value.display;
        node.setAttribute("datetime", new Date().toISOString());
    });
    document.querySelectorAll("[data-auto-recorded-at]").forEach((input) => {
        input.value = value.input;
    });
}

function addAutomaticDateTimeToCreateForm(root = document) {
    const heading = root.querySelector?.("h1")?.textContent?.trim() || document.querySelector("h1")?.textContent?.trim() || "";
    const path = window.location.pathname;
    const isCreatePage = /\/(create|add)\//.test(path)
        || /(إضافة|تسجيل|شراء|تحصيل|مصروف|تحويل|استلام|مرتجع|تسوية|تعيين|تسليم)/.test(heading);
    if (!isCreatePage) return;

    const forms = Array.from(root.querySelectorAll?.(".page-content form") || document.querySelectorAll(".page-content form"));
    const form = forms.find((candidate) => {
        if (candidate.dataset.autoDateTimeReady || candidate.querySelector("input[type='datetime-local']")) return false;
        return candidate.querySelector("input:not([type='hidden']), select, textarea");
    });
    if (!form) return;
    form.dataset.autoDateTimeReady = "1";
    const label = document.createElement("label");
    label.className = "auto-recorded-at-field";
    const title = document.createElement("span");
    title.textContent = "التاريخ والوقت (يسجل تلقائيًا)";
    const input = document.createElement("input");
    input.type = "datetime-local";
    input.readOnly = true;
    input.dataset.autoRecordedAt = "true";
    label.append(title, input);
    const csrf = form.querySelector("input[name='csrfmiddlewaretoken']");
    if (csrf?.nextSibling) form.insertBefore(label, csrf.nextSibling);
    else form.prepend(label);
    updateLiveDateTime();
}

updateLiveDateTime();
window.setInterval(updateLiveDateTime, 1000);

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

const UNSAVED_FORM_MESSAGE = "\u0644\u062f\u064a\u0643 \u0628\u064a\u0627\u0646\u0627\u062a \u063a\u064a\u0631 \u0645\u062d\u0641\u0648\u0638\u0629. \u0625\u0630\u0627 \u0627\u0646\u062a\u0642\u0644\u062a \u0627\u0644\u0622\u0646 \u0644\u0646 \u064a\u062a\u0645 \u062d\u0641\u0638\u0647\u0627. \u0647\u0644 \u062a\u0631\u064a\u062f \u0627\u0644\u0645\u062a\u0627\u0628\u0639\u0629\u061f";
const trackedFormSnapshots = new WeakMap();
let allowUnsavedNavigation = false;

function getFormMethod(form) {
    return String(form.getAttribute("method") || form.method || "get").toLowerCase();
}

function hasEditableFields(form) {
    return Boolean(form.querySelector([
        "textarea",
        "select",
        "input:not([type='button']):not([type='hidden']):not([type='reset']):not([type='submit'])",
    ].join(",")));
}

function shouldTrackUnsavedForm(form) {
    if (!(form instanceof HTMLFormElement)) return false;
    if (form.dataset.unsavedGuard === "off" || form.closest("[data-unsaved-guard='off']")) return false;
    if (form.dataset.confirm) return false;
    if (getFormMethod(form) !== "post" && form.dataset.unsavedGuard !== "on") return false;
    return hasEditableFields(form);
}

function shouldSkipUnsavedField(key, value) {
    if (!key || key === "csrfmiddlewaretoken") return true;
    return value instanceof File && !value.name && value.size === 0;
}

function formSnapshot(form) {
    const entries = [];
    const formData = new FormData(form);
    formData.forEach((value, key) => {
        if (shouldSkipUnsavedField(key, value)) return;
        if (value instanceof File) {
            entries.push([key, "file", value.name, value.size, value.lastModified || 0]);
            return;
        }
        entries.push([key, "value", String(value)]);
    });
    return JSON.stringify(entries);
}

function trackUnsavedForm(form, reset = false) {
    if (!shouldTrackUnsavedForm(form)) return false;
    if (reset || !trackedFormSnapshots.has(form)) {
        trackedFormSnapshots.set(form, formSnapshot(form));
    }
    return true;
}

function getDirtyUnsavedForms() {
    const dirtyForms = [];
    document.querySelectorAll("form").forEach((form) => {
        if (!trackUnsavedForm(form)) return;
        if (trackedFormSnapshots.get(form) !== formSnapshot(form)) {
            dirtyForms.push(form);
        }
    });
    return dirtyForms;
}

function hasDirtyUnsavedForms() {
    return getDirtyUnsavedForms().length > 0;
}

function markUnsavedFormSaved(form) {
    if (form) {
        trackUnsavedForm(form, true);
    } else {
        document.querySelectorAll("form").forEach((candidate) => trackUnsavedForm(candidate, true));
    }
}

function setupUnsavedFormTracking(root = document) {
    const forms = root.matches?.("form") ? [root] : Array.from(root.querySelectorAll?.("form") || []);
    forms.forEach((form) => trackUnsavedForm(form));
}

function allowCurrentNavigation() {
    allowUnsavedNavigation = true;
    window.setTimeout(() => {
        allowUnsavedNavigation = false;
    }, 1200);
}

function isPageNavigationLink(link, event) {
    if (!link || event.defaultPrevented) return false;
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return false;
    if (link.hasAttribute("download")) return false;
    const target = (link.getAttribute("target") || "_self").toLowerCase();
    if (target !== "_self") return false;
    const url = new URL(link.href, window.location.href);
    if (url.origin !== window.location.origin) return false;
    return url.pathname !== window.location.pathname || url.search !== window.location.search;
}

window.SHUnsavedForms = {
    hasDirtyForms: hasDirtyUnsavedForms,
    markSaved: markUnsavedFormSaved,
    reset: markUnsavedFormSaved,
};

setupUnsavedFormTracking();

document.addEventListener("DOMContentLoaded", () => {
    setupUnsavedFormTracking();
});

function normalizeNumberText(value) {
    let normalized = String(value ?? '')
        .trim()
        .replace(/[٠-٩]/g, digit => String('٠١٢٣٤٥٦٧٨٩'.indexOf(digit)))
        .replace(/[۰-۹]/g, digit => String('۰۱۲۳۴۵۶۷۸۹'.indexOf(digit)))
        .replace(/٬/g, '')
        .replace(/٫/g, '.');
    if (normalized.includes('.')) return normalized.replace(/,/g, '');
    const commaParts = normalized.split(',');
    // A single comma followed by one or two digits is a decimal separator,
    // not a thousands separator. Normalize it to the system-wide dot.
    if (commaParts.length === 2 && /^\d{1,2}$/.test(commaParts[1])) {
        return `${commaParts[0]}.${commaParts[1]}`;
    }
    return normalized.replace(/,/g, '');
}

function formatExactNumber(value) {
    const normalized = normalizeNumberText(value);
    if (!/^-?\d+(\.\d+)?$/.test(normalized)) return String(value ?? '');
    const sign = normalized.startsWith('-') ? '-' : '';
    const unsigned = sign ? normalized.slice(1) : normalized;
    const [integer, fraction] = unsigned.split('.');
    const grouped = integer.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    return `${sign}${grouped}${fraction === undefined ? '' : `.${fraction}`}`;
}

window.SHNumbers = { normalize: normalizeNumberText, format: formatExactNumber };

function enhanceSharedPageUi(root = document) {
    root.querySelectorAll('input[type="number"]').forEach(input => {
        // Keep the browser control aligned with the backend/JSON decimal
        // convention regardless of the surrounding Arabic page language.
        input.lang = 'en';
        if (input.step === 'any' || String(input.step).includes('.')) input.inputMode = 'decimal';
    });
    const pageContent = root.closest?.('[data-page-content]') || document.querySelector('[data-page-content]');
    const paginatedTable = pageContent?.querySelector('table');
    root.querySelectorAll('table').forEach((table) => {
        if (table.dataset.countEnhanced) return;
        table.dataset.countEnhanced = '1';
        const rows = [...table.querySelectorAll('tbody tr')].filter(row => !row.querySelector('td[colspan]'));
        const badge = document.createElement('div');
        badge.className = 'table-record-count';
        // The paginator count belongs only to the page's primary table. Using
        // it for every table made all secondary tables show the same total.
        const paginatedCount = table === paginatedTable ? pageContent?.dataset.totalRecords : null;
        const tableCount = paginatedCount !== undefined && paginatedCount !== null && paginatedCount !== ''
            ? paginatedCount
            : rows.length;
        badge.textContent = `إجمالي العدد: ${formatExactNumber(String(tableCount))}`;
        badge.classList.add('number-value');
        table.parentElement?.insertBefore(badge, table);
    });
    root.querySelectorAll('td, .stat-card strong, .summary-value, [data-number]').forEach((node) => {
        if (node.children.length || node.dataset.numberEnhanced) return;
        const raw = normalizeNumberText(node.textContent);
        if (!/^-?\d+(\.\d+)?$/.test(raw)) return;
        node.dataset.numberEnhanced = '1';
        // Format the string directly. Converting through Number used to round
        // large values and could silently change the displayed value.
        node.textContent = formatExactNumber(raw);
        node.classList.add('number-value');
    });
    root.querySelectorAll('form').forEach((form) => {
        if (form.dataset.submitGuard) return;
        form.dataset.submitGuard = '1';
        if ((form.method || 'get').toLowerCase() === 'post' && !form.querySelector('[name="_submission_token"]')) {
            const token = document.createElement('input');
            token.type = 'hidden'; token.name = '_submission_token';
            token.value = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
            form.appendChild(token);
        }
        form.addEventListener('submit', (event) => {
            if (!form.checkValidity()) return;
            if (form.dataset.submitting === '1') { event.preventDefault(); return; }
            form.dataset.submitting = '1';
            setTimeout(() => form.querySelectorAll('button[type="submit"], input[type="submit"]').forEach(button => {
                button.disabled = true; button.dataset.originalText = button.textContent; button.textContent = 'جارٍ الحفظ...';
            }), 0);
        });
    });
}
document.addEventListener('DOMContentLoaded', () => enhanceSharedPageUi());
document.addEventListener('DOMContentLoaded', () => addAutomaticDateTimeToCreateForm());
document.addEventListener('sh:page-loaded', () => {
    enhanceSharedPageUi();
    addAutomaticDateTimeToCreateForm();
});

new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
        mutation.addedNodes.forEach((node) => {
            if (node instanceof Element) setupUnsavedFormTracking(node);
        });
    });
}).observe(document.documentElement, { childList: true, subtree: true });

document.addEventListener("input", (event) => {
    trackUnsavedForm(event.target.closest?.("form"));
}, true);

document.addEventListener("change", (event) => {
    trackUnsavedForm(event.target.closest?.("form"));
}, true);

document.addEventListener("click", (event) => {
    const link = event.target.closest?.("a[href]");
    if (!isPageNavigationLink(link, event) || !hasDirtyUnsavedForms()) return;
    if (window.confirm(UNSAVED_FORM_MESSAGE)) {
        allowCurrentNavigation();
        return;
    }
    event.preventDefault();
    event.stopImmediatePropagation();
}, true);

window.addEventListener("beforeunload", (event) => {
    if (allowUnsavedNavigation || !hasDirtyUnsavedForms()) return;
    event.preventDefault();
    event.returnValue = "";
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
    if (!event.defaultPrevented) {
        markUnsavedFormSaved(form);
        allowCurrentNavigation();
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

// Content tabs use delegation so they also work after workspace navigation
// replaces the page content without firing DOMContentLoaded again.
document.addEventListener("click", (event) => {
    const contentTab = event.target.closest(".tabs-container .tab-btn[data-tab]");
    if (!contentTab) return;

    const container = contentTab.closest(".tabs-container");
    const target = [...container.querySelectorAll(".tab-content")]
        .find(panel => panel.id === contentTab.dataset.tab);
    if (!target) return;

    container.querySelectorAll(".tab-btn").forEach(tab => {
        const isActive = tab === contentTab;
        tab.classList.toggle("active", isActive);
        tab.setAttribute("aria-selected", String(isActive));
    });
    container.querySelectorAll(".tab-content").forEach(panel => {
        panel.classList.toggle("active", panel === target);
    });
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
document.addEventListener('change', function (event) {
    const periodSelect = event.target.closest('[data-period-select]');
    if (!periodSelect) return;
    const fields = periodSelect.closest('[data-period-filter]')?.querySelector('[data-custom-period-fields]');
    if (!fields) return;
    const isCustom = periodSelect.value === 'custom';
    fields.classList.toggle('is-open', isCustom);
    fields.querySelectorAll('input').forEach((input) => { input.disabled = !isCustom; });
    if (isCustom) fields.querySelector('input')?.focus();
});

document.querySelectorAll('[data-period-filter]').forEach((filter) => {
    const select = filter.querySelector('[data-period-select]');
    const fields = filter.querySelector('[data-custom-period-fields]');
    if (!select || !fields) return;
    const isCustom = select.value === 'custom';
    fields.classList.toggle('is-open', isCustom);
    fields.querySelectorAll('input').forEach((input) => { input.disabled = !isCustom; });
});
