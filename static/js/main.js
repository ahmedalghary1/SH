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

const isAuthPage = !document.body.dataset.pwaUserId;
let requestedPwaUpdate = false;

if ("serviceWorker" in navigator && isAuthPage) {
    navigator.serviceWorker.controller?.postMessage({ type: "CLEAR_SCOPE" });
}

if ("serviceWorker" in navigator && !isAuthPage) {
    window.addEventListener("load", () => {
        navigator.serviceWorker.register("/service-worker.js", { scope: "/" })
            .then((registration) => {
                const offerUpdate = () => {
                    if (!registration.waiting || !navigator.serviceWorker.controller) return;
                    showPwaNotice("يتوفر تحديث للتطبيق. احفظ عملك ثم اضغط تحديث التطبيق.");
                    const notice = document.querySelector("[data-pwa-notice]");
                    const button = document.createElement("button");
                    button.type = "button";
                    button.className = "btn btn-light btn-small";
                    button.textContent = "تحديث التطبيق";
                    button.addEventListener("click", async () => {
                        const status = await window.SHSync?.getQueueStatus?.();
                        if (window.SHUi?.hasUnsavedChanges?.() || Number(status?.pending || status?.total || 0) > 0) {
                            showPwaNotice("احفظ التغييرات وزامن العمليات المعلقة قبل تحديث التطبيق.", true);
                            return;
                        }
                        requestedPwaUpdate = true;
                        registration.waiting?.postMessage({ type: "SKIP_WAITING" });
                    });
                    notice?.appendChild(button);
                    window.clearTimeout(showPwaNotice.timer);
                };
                offerUpdate();
                registration.addEventListener("updatefound", () => {
                    const worker = registration.installing;
                    worker?.addEventListener("statechange", () => {
                        if (worker.state === "installed") offerUpdate();
                    });
                });
                return registration.update?.();
            })
            .catch((error) => {
                console.warn("Service worker registration failed", error);
            });
    });
}

if ("serviceWorker" in navigator) {
    navigator.serviceWorker.addEventListener("controllerchange", () => {
        if (requestedPwaUpdate) window.location.reload();
    });
}

function showPwaNotice(message, isError = false) {
    let notice = document.querySelector("[data-pwa-notice]");
    if (!notice) {
        notice = document.createElement("div");
        notice.dataset.pwaNotice = "true";
        notice.setAttribute("role", "status");
        notice.setAttribute("aria-live", "polite");
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

async function requestJson(url, options = {}) {
    const method = (options.method || 'GET').toUpperCase();
    const isRead = method === 'GET' || method === 'HEAD';
    if (navigator.onLine === false && window.SHOffline?.handleJsonRequest) {
        const payload = await window.SHOffline.handleJsonRequest(url, options);
        if (payload?.success === false) throw new Error(payload.message || 'تعذر تنفيذ العملية على الجهاز.');
        return payload;
    }
    let response;
    try {
        response = await fetch(url, { credentials: 'same-origin', ...options });
    } catch (error) {
        // A server may have committed a POST before its response was lost.
        // Falling back to the offline queue afterwards would duplicate it.
        if (isRead && error.name !== 'AbortError' && window.SHOffline?.handleJsonRequest) {
            try { return await window.SHOffline.handleJsonRequest(url, options); } catch (_offlineError) { /* Show the original connection failure. */ }
        }
        if (error.name === 'AbortError') throw error;
        throw new Error(isRead ? 'تعذر الاتصال. تحقق من الإنترنت ثم حاول مرة أخرى.' : 'تعذر تأكيد نتيجة الحفظ. تحقق من السجلات قبل إعادة المحاولة.');
    }
    if (!(response.headers.get('content-type') || '').includes('application/json')) {
        throw new Error(response.redirected ? 'انتهت الجلسة. حدّث الصفحة ثم سجّل الدخول مجددًا.' : 'تعذر الاتصال بالخادم. حاول مرة أخرى.');
    }
    let payload;
    try { payload = await response.json(); } catch (_error) { throw new Error('استجابة الخادم غير مكتملة. حاول مرة أخرى.'); }
    if (!response.ok || payload?.success === false) throw new Error(payload?.message || 'تعذر تنفيذ العملية. حاول مرة أخرى.');
    return payload;
}
window.SHHttp = { json: requestJson };

function enhanceResponsiveTables(root = document) {
    const tables = root.querySelectorAll?.(".page-content table, table") || [];

    tables.forEach((table) => {
        if (table.closest(".invoice-box, .receipt-invoice")) return;

        let region = table.closest(
            ".table-wrap, .cash-table-wrap, .stock-table-wrap, .items-table-wrap, .invoice-items, .responsive-table-region"
        );
        if (!region) {
            region = document.createElement("div");
            region.className = "table-wrap responsive-table-region auto-table-wrap";
            table.parentNode.insertBefore(region, table);
            region.appendChild(table);
        } else {
            region.classList.add("responsive-table-region");
        }

        const bodyRows = table.querySelectorAll("tbody tr").length;
        region.classList.toggle("long-table-region", bodyRows > 8);
        if (!region.hasAttribute("tabindex")) region.tabIndex = 0;
        region.setAttribute("role", "region");

        if (!region.hasAttribute("aria-label")) {
            const section = table.closest("section, .card, .tab-content, .page-content");
            const heading = section?.querySelector("h1, h2, h3")?.textContent?.trim();
            const caption = table.querySelector("caption")?.textContent?.trim();
            region.setAttribute("aria-label", caption || heading || "جدول البيانات");
        }

        if (region.dataset.overflowReady) return;
        region.dataset.overflowReady = "1";
        const updateOverflowState = () => {
            region.classList.toggle("is-scrollable-x", region.scrollWidth > region.clientWidth + 2);
            region.classList.toggle("is-at-scroll-end", Math.abs(region.scrollLeft) + region.clientWidth >= region.scrollWidth - 3);
        };
        region.addEventListener("scroll", updateOverflowState, { passive: true });
        window.requestAnimationFrame(updateOverflowState);

        if ("ResizeObserver" in window) {
            window.SHTableResizeObserver ||= new ResizeObserver((entries) => {
                entries.forEach((entry) => {
                    const node = entry.target;
                    node.classList.toggle("is-scrollable-x", node.scrollWidth > node.clientWidth + 2);
                });
            });
            window.SHTableResizeObserver.observe(region);
        }
    });
}

function enhanceSharedPageUi(root = document) {
    enhanceResponsiveTables(root);
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
        const region = table.closest('.responsive-table-region');
        if (region?.parentElement) region.parentElement.insertBefore(badge, region);
        else table.parentElement?.insertBefore(badge, table);
    });
    root.querySelectorAll('td, .stat-card strong, .summary-value, [data-number]').forEach((node) => {
        if (node.children.length || node.dataset.numberEnhanced) return;
        const raw = normalizeNumberText(node.textContent);
        if (!/^-?\d+(\.\d+)?$/.test(raw)) return;
        // A plain integer cell may be a phone number, SKU, or document ID.
        // Group only explicit numeric fields or decimal amounts in tables.
        if (node.tagName === 'TD' && !node.hasAttribute('data-number') && !raw.includes('.')) return;
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
            token.value = window.crypto?.randomUUID ? window.crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
            form.appendChild(token);
        }
        form.addEventListener('submit', (event) => {
            if (event.defaultPrevented || (!form.noValidate && !event.submitter?.formNoValidate && !form.checkValidity())) return;
            const target = event.submitter?.getAttribute('formtarget') || form.target;
            const action = event.submitter?.getAttribute('formaction') || form.getAttribute('action') || window.location.href;
            if ((target && target !== '_self') || /\/(export[^/]*|print|report-print|download)(\/|\?|$)/.test(action)) return;
            if (form.dataset.submitting === '1') { event.preventDefault(); return; }
            form.dataset.submitting = '1';
            // Validation, confirmations, and offline handlers may cancel later
            // in the same event. Do not leave the form locked in that case.
            setTimeout(() => {
                if (event.defaultPrevented) { resetFormSubmission(form); return; }
                form.setAttribute('aria-busy', 'true');
                form.querySelectorAll('button[type="submit"], button:not([type]), input[type="submit"]').forEach(button => {
                    if (button.disabled) return;
                    button.dataset.submitDisabled = '1';
                    button.disabled = true;
                    button.dataset.originalText = button.tagName === 'INPUT' ? button.value : button.textContent;
                    if (button.tagName === 'INPUT') button.value = 'جارٍ الحفظ...';
                    else button.textContent = 'جارٍ الحفظ...';
                });
            }, 0);
        });
        form.addEventListener('input', () => {
            if ((form.method || 'get').toLowerCase() === 'post') form.dataset.unsaved = '1';
        });
        form.addEventListener('change', () => {
            if ((form.method || 'get').toLowerCase() === 'post') form.dataset.unsaved = '1';
        });
    });
}

function resetFormSubmission(form) {
    delete form.dataset.submitting;
    form.removeAttribute('aria-busy');
    form.querySelectorAll('[data-submit-disabled]').forEach(button => {
        button.disabled = false;
        if (button.tagName === 'INPUT') button.value = button.dataset.originalText;
        else button.textContent = button.dataset.originalText;
        delete button.dataset.submitDisabled;
        delete button.dataset.originalText;
    });
}
window.SHUi = {
    resetFormSubmission,
    hasUnsavedChanges: () => Boolean(document.querySelector('form[data-unsaved="1"]')) || Boolean(window.SHWorkspace?.hasUnsavedChanges?.()),
};
window.addEventListener('pageshow', () => document.querySelectorAll('form[data-submitting="1"]').forEach(resetFormSubmission));
document.addEventListener('DOMContentLoaded', () => enhanceSharedPageUi());
document.addEventListener('DOMContentLoaded', () => addAutomaticDateTimeToCreateForm());
document.addEventListener('sh:page-loaded', () => {
    enhanceSharedPageUi();
    addAutomaticDateTimeToCreateForm();
    enhanceListControls();
    setupPasswordToggles();
    setupStockWarehouseFilters();
    setupDatePeriodFilters();
    updateActiveNavigation();
    setupFormAccessibility();
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
    if (missingCombo && !form.noValidate && !event.submitter?.formNoValidate) {
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
    modal.returnFocusTo = document.activeElement;
    modal.hidden = false;
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
    const heading = modal.querySelector('h2, h3');
    if (heading) {
        heading.id ||= `${modal.id || 'modal'}-title`;
        modal.setAttribute('aria-labelledby', heading.id);
    }
    document.body.classList.add("modal-open");
    const firstField = modal.querySelector("input:not([type='hidden']):not(.combo-source):not(:disabled), select:not(.combo-source):not(:disabled), textarea:not(:disabled), button:not(:disabled), a[href]");
    firstField?.focus({ preventScroll: true });
}

function closeModal(modal) {
    if (!modal) return;
    modal.hidden = true;
    if (modal.returnFocusTo?.isConnected) modal.returnFocusTo.focus({ preventScroll: true });
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
    input?.removeAttribute('aria-activedescendant');
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
    option.tabIndex = -1;
    return option;
}

let comboSequence = 0;
function setupComboAria(input, list, source = input) {
    list.id ||= `sh-combo-list-${++comboSequence}`;
    input.setAttribute('aria-controls', list.id);
    input.setAttribute('aria-autocomplete', 'list');
    const label = source.labels?.[0]?.querySelector('span')?.textContent?.trim();
    const accessibleLabel = source.getAttribute('aria-label') || label;
    if (accessibleLabel) input.setAttribute('aria-label', accessibleLabel);
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
    select.setAttribute('aria-hidden', 'true');
    setupComboAria(input, list, select);

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
        if (select.value || select.disabled) input.setCustomValidity('');
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
        // Clearing the hidden source dispatches change and syncInput. Keep the
        // user's search text visible until they choose a replacement option.
        if (!exact) input.value = typed;
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
    setupComboAria(input, list);

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
        let requestNumber = 0;

        async function updateWarehouses() {
            const thisRequest = ++requestNumber;
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
                const payload = await requestJson(`/inventory/ajax/variant-warehouses/?variant_id=${encodeURIComponent(variantId)}&scope=${encodeURIComponent(scope)}`);
                if (thisRequest !== requestNumber) return;
                const warehouses = payload.data?.warehouses || [];
                warehouseSelect.disabled = warehouses.length === 0;
                setWarehouseOptions(
                    warehouseSelect,
                    warehouses,
                    warehouses.length ? initialPlaceholder : "غير متاح في المخازن",
                    selectedValue,
                );
            } catch (error) {
                if (thisRequest !== requestNumber) return;
                warehouseSelect.disabled = true;
                setWarehouseOptions(warehouseSelect, [], error.message || "تعذر تحميل المخازن");
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
            .catch(() => showPwaNotice('تعذرت المزامنة. تحقق من الاتصال ثم حاول مرة أخرى.', true))
            .finally(() => {
                syncButton.disabled = false;
            });
    }

});

document.addEventListener("DOMContentLoaded", () => {
    enhanceListControls();
    setupPasswordToggles();
    setupStockWarehouseFilters();
    setupDatePeriodFilters();
    setupFormAccessibility();
    updateActiveNavigation();
});

function updateActiveNavigation() {
    const currentPath = window.location.pathname;
    document.querySelectorAll(".side-nav a").forEach((link) => {
        link.classList.remove('is-active');
        link.removeAttribute('aria-current');
        const linkPath = new URL(link.href, window.location.origin).pathname;
        if (linkPath === currentPath || (linkPath !== "/" && currentPath.startsWith(linkPath))) {
            link.classList.add("is-active");
            link.setAttribute('aria-current', 'page');
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
}

function setupFormAccessibility(root = document) {
    root.querySelectorAll('form label').forEach((label) => {
        const input = label.querySelector('input:not([type="hidden"]):not(.combo-source), select, textarea');
        const error = label.querySelector('.error');
        if (!input || !error) return;
        error.id ||= `${input.id || `field-${++comboSequence}`}-error`;
        input.setAttribute('aria-invalid', 'true');
        input.setAttribute('aria-describedby', [...new Set([...(input.getAttribute('aria-describedby') || '').split(' '), error.id].filter(Boolean))].join(' '));
    });
    root.querySelectorAll('.form-errors').forEach((error) => error.setAttribute('role', 'alert'));
    root.querySelectorAll('.modal:not([hidden])').forEach(openModal);
}

function setSidebarState(isOpen, { restoreFocus = false } = {}) {
    const body = document.body;
    const toggle = document.querySelector("[data-sidebar-toggle]");
    const sidebar = document.querySelector(".sidebar");
    body.classList.toggle("sidebar-open", isOpen);
    toggle?.setAttribute("aria-expanded", String(isOpen));
    sidebar?.setAttribute("aria-hidden", String(!isOpen && window.matchMedia("(max-width: 61.25rem)").matches));
    if (isOpen) sidebar?.querySelector("[data-sidebar-close], a, button")?.focus({ preventScroll: true });
    else if (restoreFocus) toggle?.focus({ preventScroll: true });
}

const compactNavigation = window.matchMedia("(max-width: 61.25rem)");
const syncSidebarForViewport = () => {
    if (!compactNavigation.matches) setSidebarState(false);
    else document.querySelector(".sidebar")?.setAttribute("aria-hidden", String(!document.body.classList.contains("sidebar-open")));
};
compactNavigation.addEventListener?.("change", syncSidebarForViewport);
document.addEventListener("DOMContentLoaded", syncSidebarForViewport);

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
        setSidebarState(!document.body.classList.contains("sidebar-open"));
    }

    if (event.target.closest("[data-sidebar-close]") || event.target.closest(".side-nav a")) {
        setSidebarState(false, { restoreFocus: Boolean(event.target.closest("[data-sidebar-close]")) });
    }
});

document.addEventListener("keydown", (event) => {
    const input = event.target.closest('.combo-input');
    const combo = input?.closest('.combo-field');
    if (combo && ['ArrowDown', 'ArrowUp', 'Enter', 'Escape'].includes(event.key)) {
        if (event.key === 'Escape') {
            closeCombo(combo);
            event.preventDefault();
            return;
        }
        if (event.key !== 'Enter' && !combo.classList.contains('is-open')) combo.querySelector('.combo-toggle')?.click();
        const options = [...combo.querySelectorAll('.combo-list button:not(:disabled)')];
        const current = options.findIndex(option => option.classList.contains('is-keyboard-active'));
        if (event.key === 'Enter') {
            if (combo.classList.contains('is-open') && options[current]) {
                event.preventDefault();
                options[current].click();
            }
        } else if (options.length) {
            event.preventDefault();
            const next = current < 0 ? (event.key === 'ArrowUp' ? options.length - 1 : 0) : (current + (event.key === 'ArrowUp' ? -1 : 1) + options.length) % options.length;
            options.forEach((option, index) => option.classList.toggle('is-keyboard-active', index === next));
            options[next].id ||= `sh-combo-option-${++comboSequence}`;
            input.setAttribute('aria-activedescendant', options[next].id);
            options[next].scrollIntoView?.({ block: 'nearest' });
        }
    }
    const modal = document.querySelector('.modal:not([hidden])');
    if (modal && event.key === 'Escape') {
        event.preventDefault();
        closeModal(modal);
        return;
    }
    if (modal && event.key === 'Tab') {
        const fields = [...modal.querySelectorAll('input:not([type="hidden"]):not(.combo-source), select:not(.combo-source), textarea, button, a[href], [tabindex="0"]')].filter(node => !node.disabled && node.getClientRects().length && node.tabIndex !== -1);
        const first = fields[0];
        const last = fields[fields.length - 1];
        if (event.shiftKey && (document.activeElement === first || !modal.contains(document.activeElement))) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
    if (event.key === 'Escape') {
        closeAllCombos();
        if (document.body.classList.contains("sidebar-open")) setSidebarState(false, { restoreFocus: true });
    }
});

document.addEventListener('focusout', event => {
    const combo = event.target.closest('.combo-field');
    if (combo) setTimeout(() => { if (!combo.contains(document.activeElement)) closeCombo(combo); }, 0);
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

function setupDatePeriodFilters(root = document) {
root.querySelectorAll('[data-period-filter]').forEach((filter) => {
    const select = filter.querySelector('[data-period-select]');
    const fields = filter.querySelector('[data-custom-period-fields]');
    if (!select || !fields) return;
    const isCustom = select.value === 'custom';
    fields.classList.toggle('is-open', isCustom);
    fields.querySelectorAll('input').forEach((input) => { input.disabled = !isCustom; });
});
}
