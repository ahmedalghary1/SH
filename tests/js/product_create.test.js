const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

class FakeElement {
    constructor(tagName = "div") {
        this.tagName = tagName.toUpperCase();
        this.attributes = {};
        this.children = [];
        this.dataset = {};
        this.listeners = {};
        this.checkboxes = [];
        this.hidden = false;
        this.textContent = "";
        this.value = "";
    }

    addEventListener(type, listener) {
        (this.listeners[type] ||= []).push(listener);
    }

    emit(type) {
        for (const listener of this.listeners[type] || []) listener({ target: this });
    }

    append(...children) {
        this.children.push(...children);
    }

    appendChild(child) {
        this.children.push(child);
        return child;
    }

    replaceChildren(...children) {
        this.children = [...children];
    }

    setAttribute(name, value) {
        this.attributes[name] = String(value);
    }

    setCustomValidity(message) {
        this.validationMessage = message;
    }

    querySelector(selector) {
        return this.elementsBySelector?.[selector] || null;
    }

    querySelectorAll(selector) {
        if (selector === 'input[type="checkbox"]:checked') {
            return this.checkboxes.filter((checkbox) => checkbox.checked);
        }
        if (selector === 'input[type="checkbox"]') return [...this.checkboxes];
        if (this.tagName === "INPUT" && this.type === "number") return [this];
        if (selector === 'input[type="number"]') {
            return this.children.flatMap((child) => child.querySelectorAll(selector));
        }
        return this.children.flatMap((child) => child.querySelectorAll?.(selector) || []);
    }
}

function checkbox(value, label, checked = false) {
    const input = new FakeElement("input");
    input.type = "checkbox";
    input.value = String(value);
    input.dataset.label = label;
    input.checked = checked;
    return input;
}

function createFixture({ selected = true } = {}) {
    const form = new FakeElement("form");
    const colors = new FakeElement("div");
    const sizes = new FakeElement("div");
    const rows = new FakeElement("tbody");
    const empty = new FakeElement("p");
    rows.dataset.maxQuantity = "2147483647";

    colors.checkboxes = [
        checkbox(1, "أحمر", selected),
        checkbox(2, "أزرق", false),
    ];
    sizes.checkboxes = [
        checkbox(10, "M", selected),
        checkbox(20, "L", selected),
    ];
    form.elementsBySelector = {
        "#product-color-choices": colors,
        "#product-size-choices": sizes,
        "#variant-quantity-rows": rows,
        "#variant-table-empty": empty,
    };
    return { form, colors, sizes, rows, empty };
}

function rowInputs(rows) {
    return rows.querySelectorAll('input[type="number"]');
}

test("renders every selected color/size combination and survives workspace navigation", () => {
    const first = createFixture();
    const initialQuantities = { textContent: JSON.stringify({ "1:20": "7" }) };
    const documentListeners = {};
    const fakeDocument = {
        activeForm: first.form,
        querySelector(selector) {
            return selector === "[data-product-create-form]" ? this.activeForm : null;
        },
        getElementById(id) {
            return id === "initial-variant-quantities" ? initialQuantities : null;
        },
        createElement(tagName) {
            return new FakeElement(tagName);
        },
        addEventListener(type, listener) {
            (documentListeners[type] ||= []).push(listener);
        },
        emit(type) {
            for (const listener of documentListeners[type] || []) listener();
        },
    };

    const source = fs.readFileSync(
        path.resolve(__dirname, "../../static/js/product_create.js"),
        "utf8",
    );
    vm.runInNewContext(source, { document: fakeDocument });

    assert.equal(first.rows.children.length, 2);
    assert.deepEqual(rowInputs(first.rows).map((input) => input.name), [
        "quantity_1_10",
        "quantity_1_20",
    ]);
    assert.deepEqual(rowInputs(first.rows).map((input) => input.value), ["0", "7"]);
    assert.equal(first.empty.hidden, true);

    rowInputs(first.rows)[0].value = "4";
    first.colors.checkboxes[1].checked = true;
    first.colors.emit("change");
    assert.equal(first.rows.children.length, 4);
    assert.equal(rowInputs(first.rows)[0].value, "4");

    const second = createFixture({ selected: false });
    second.colors.checkboxes[1].checked = true;
    second.sizes.checkboxes[0].checked = true;
    fakeDocument.activeForm = second.form;
    fakeDocument.emit("sh:page-loaded");
    assert.equal(second.form.dataset.productCreateInitialized, "1");
    assert.equal(second.rows.children.length, 1);
    assert.equal(rowInputs(second.rows)[0].name, "quantity_2_10");

    fakeDocument.emit("sh:page-loaded");
    assert.equal(second.colors.listeners.change.length, 1);
});

test("product builder deployment invalidates both static URL and service-worker cache", () => {
    const template = fs.readFileSync(
        path.resolve(__dirname, "../../templates/products/create.html"),
        "utf8",
    );
    const serviceWorker = fs.readFileSync(
        path.resolve(__dirname, "../../static/service-worker.js"),
        "utf8",
    );

    assert.match(template, /product_create\.js' %\}\?v=20260808-01/);
    assert.match(serviceWorker, /sh-pwa-v2026-08-08-product-variants-01/);
    assert.doesNotMatch(serviceWorker, /sh-pwa-v2026-07-11-workspace-tabs-02/);
});
