const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..", "..");
const css = fs.readFileSync(path.join(root, "static", "css", "main.css"), "utf8");
const base = fs.readFileSync(path.join(root, "templates", "base.html"), "utf8");
const navbar = fs.readFileSync(path.join(root, "templates", "partials", "navbar.html"), "utf8");

test("authenticated pages opt into safe-area viewport rendering", () => {
    assert.match(base, /width=device-width, initial-scale=1, viewport-fit=cover/);
    assert.match(css, /env\(safe-area-inset-right\)/);
    assert.match(css, /env\(safe-area-inset-bottom\)/);
});

test("responsive breakpoints cover tablet, phone, and narrow phone layouts", () => {
    assert.match(css, /max-width: 61\.25rem/);
    assert.match(css, /max-width: 48rem/);
    assert.match(css, /max-width: 32rem/);
    assert.match(css, /max-height: 32rem/);
});

test("topbar only reserves a branch row when the selector exists", () => {
    assert.match(navbar, /topbar\{% if request\.user\.is_superuser %\} has-branch-selector/);
    assert.match(css, /\.topbar\.has-branch-selector/);
    assert.match(css, /\.topbar:not\(\.has-branch-selector\)/);
});

test("dense content remains contained and horizontally scrollable", () => {
    assert.match(css, /\.responsive-table-region[\s\S]*overflow: auto/);
    assert.match(css, /\.invoice-items[\s\S]*overflow: auto/);
    assert.match(css, /\.page-content > \*/);
    assert.match(css, /input\[type="datetime-local"\]/);
});
