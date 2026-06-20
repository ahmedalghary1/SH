function text(value, fallback = "") {
  return String(value || fallback || "").trim();
}

function normalize(value) {
  return text(value)
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
  combo?.classList.remove("is-open");
  combo?.querySelector(".combo-input")?.setAttribute("aria-expanded", "false");
}

function closeAllCombos(except = null) {
  document.querySelectorAll(".combo-field.is-open").forEach((combo) => {
    if (combo !== except) closeCombo(combo);
  });
}

function optionButton(label, value, selected) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "combo-option";
  button.textContent = label || value || "-";
  button.dataset.value = value;
  button.setAttribute("role", "option");
  button.setAttribute("aria-selected", String(selected));
  return button;
}

export function enhanceSelect(select) {
  if (select.dataset.comboReady || select.multiple || select.closest(".combo-field")) return;
  if (select.dataset.nativeSelect !== undefined) return;

  select.dataset.comboReady = "true";
  const combo = document.createElement("div");
  combo.className = "combo-field";
  const input = document.createElement("input");
  input.type = "text";
  input.className = "combo-input";
  input.autocomplete = "off";
  input.required = select.required;
  input.disabled = select.disabled;
  input.setAttribute("role", "combobox");
  input.setAttribute("aria-expanded", "false");
  input.setAttribute("aria-haspopup", "listbox");

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "combo-toggle";
  toggle.disabled = select.disabled;
  toggle.setAttribute("aria-label", "فتح القائمة");

  const list = document.createElement("div");
  list.className = "combo-list";
  list.setAttribute("role", "listbox");

  select.parentNode.insertBefore(combo, select);
  combo.append(select, input, toggle, list);
  select.classList.add("combo-source");
  select.tabIndex = -1;

  const options = () => Array.from(select.options).map((option) => ({
    value: option.value,
    label: text(option.textContent, option.value),
    disabled: option.disabled,
    selected: option.selected
  }));

  function syncInput() {
    const selected = select.options[select.selectedIndex];
    const label = selected ? text(selected.textContent, selected.value) : "";
    input.value = selected && selected.value ? label : "";
    input.placeholder = selected && !selected.value ? label : "";
    input.title = selected && selected.value ? label : "";
    input.disabled = select.disabled;
    input.required = select.required;
    toggle.disabled = select.disabled;
    combo.classList.toggle("is-disabled", select.disabled);
  }

  function render(term = input.value) {
    const query = normalize(term);
    const filtered = options().filter((option) => {
      return !query || normalize(option.label).includes(query) || normalize(option.value).includes(query);
    });
    list.innerHTML = "";
    filtered.forEach((option) => {
      const button = optionButton(option.label, option.value, option.selected);
      button.disabled = option.disabled;
      list.appendChild(button);
    });
    if (!filtered.length) {
      const empty = document.createElement("div");
      empty.className = "combo-empty";
      empty.textContent = "لا توجد نتائج";
      list.appendChild(empty);
    }
  }

  function open(term = "") {
    if (select.disabled) return;
    closeAllCombos(combo);
    render(term);
    combo.classList.add("is-open");
    input.setAttribute("aria-expanded", "true");
  }

  function setValue(value, dispatch = true) {
    if (select.value !== value) {
      select.value = value;
      if (dispatch) select.dispatchEvent(new Event("change", { bubbles: true }));
    }
    syncInput();
  }

  input.addEventListener("focus", () => open(""));
  input.addEventListener("input", () => {
    const typed = text(input.value);
    const exact = options().find((option) => !option.disabled && normalize(option.label) === normalize(typed));
    if (exact) setValue(exact.value);
    else if (select.value) setValue("");
    open(typed);
  });
  toggle.addEventListener("click", () => {
    if (combo.classList.contains("is-open")) return closeCombo(combo);
    input.focus({ preventScroll: true });
    open("");
  });
  list.addEventListener("mousedown", (event) => event.preventDefault());
  list.addEventListener("click", (event) => {
    const option = event.target.closest(".combo-option");
    if (!option || option.disabled) return;
    setValue(option.dataset.value);
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

export function enhanceCombos(root = document) {
  root.querySelectorAll("select:not([data-native-select])").forEach(enhanceSelect);
}

document.addEventListener("click", (event) => {
  if (!event.target.closest(".combo-field")) closeAllCombos();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeAllCombos();
});
