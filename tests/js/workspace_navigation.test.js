const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

class Element {
  constructor() {
    this.children = [];
    this.dataset = {};
    this.attributes = {};
    this.scrollLeft = 0;
  }
  get firstChild() { return this.children[0]; }
  set innerHTML(value) {
    this.children = [];
    if (value) this.appendChild(new Element());
  }
  append(...items) { items.forEach(item => this.appendChild(item)); }
  appendChild(item) {
    if (item.parent) item.parent.children = item.parent.children.filter(child => child !== item);
    this.children.push(item);
    item.parent = this;
  }
  replaceChildren() { this.children = []; }
  setAttribute(key, value) { this.attributes[key] = value; }
  removeAttribute(key) { delete this.attributes[key]; }
  hasAttribute(key) { return key in this.attributes; }
  querySelector() { return null; }
}

function fixture() {
  const bar = new Element();
  const content = new Element();
  content.innerHTML = '<p>home</p>';
  const events = {};
  const stored = {};
  const location = { href: 'https://example.test/', origin: 'https://example.test', pathname: '/', search: '' };
  const document = {
    title: 'الرئيسية', body: new Element(),
    querySelector(selector) {
      if (selector === '[data-workspace-tabs]') return bar;
      if (selector === '[data-page-content]') return content;
      if (selector === 'h1') return { textContent: 'الرئيسية' };
      return null;
    },
    createElement: () => new Element(),
    dispatchEvent() {},
    addEventListener(type, listener) { events[type] = listener; },
  };
  const context = {
    document, location, URL, AbortController, CustomEvent: class {},
    window: { scrollY: 0, scrollTo() {} },
    sessionStorage: { getItem: key => stored[key], setItem: (key, value) => { stored[key] = value; } },
    history: {
      pushState(_state, _title, url) { location.pathname = url; location.search = ''; location.href = `https://example.test${url}`; },
      replaceState(_state, _title, url) { location.pathname = url; location.search = ''; location.href = `https://example.test${url}`; },
    },
    fetch: async url => ({ ok: true, redirected: false, url: String(url), headers: { get: () => 'text/html' }, text: async () => url }),
    FormData: class { constructor() { this.items = []; } append(name, value) { this.items.push([name, value]); } [Symbol.iterator]() { return this.items[Symbol.iterator](); } },
    DOMParser: class {
      parseFromString(url) {
        return {
          title: url,
          querySelector(selector) {
            if (selector === '[data-page-content]') return { innerHTML: `<p>${url}</p>`, dataset: {}, hasAttribute: () => false };
            if (selector === 'h1') return { textContent: url };
            return null;
          },
          querySelectorAll: () => [],
        };
      }
    },
    addEventListener() {}, requestAnimationFrame: callback => callback(),
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.resolve(__dirname, '../../static/js/internal-tabs.js'), 'utf8'), context);
  return { context, bar, content, stored, events };
}

test('ordinary navigation reuses the active workspace tab; explicit action opens another', async () => {
  const { context, bar, stored, events } = fixture();
  await context.window.SHWorkspace.navigate('/customers/');
  let state = JSON.parse(stored['sh-workspace-tabs-v2']);
  assert.deepEqual(state.tabs.map(tab => tab.url), ['/customers/']);

  assert.equal(bar.children[0].textContent, '＋ فتح في تبويب جديد');
  bar.children[0].onclick();
  assert.equal(bar.children[0].textContent, 'اختر الرابط الآن');
  const link = { href: 'https://example.test/orders/', target: '', hasAttribute: () => false };
  link.closest = selector => selector === 'a[href]' ? link : null;
  events.click({ target: link, button: 0, preventDefault() {} });
  await new Promise(resolve => setImmediate(resolve));
  state = JSON.parse(stored['sh-workspace-tabs-v2']);
  assert.deepEqual(state.tabs.map(tab => tab.url), ['/customers/', '/orders/']);
  assert.equal(bar.children[0].textContent, '＋ فتح في تبويب جديد');
});

test('saving in one workspace tab preserves the live form in another tab', async () => {
  const { context, bar, content, stored, events } = fixture();
  await context.window.SHWorkspace.navigate('/customers/');
  const unsavedField = new Element();
  unsavedField.value = 'customer draft';
  content.append(unsavedField);
  await context.window.SHWorkspace.openInNewTab('/orders/');

  const form = {
    attributes: { method: 'post', action: '/orders/create/' },
    getAttribute(name) { return this.attributes[name] || null; },
    setAttribute(name, value) { this.attributes[name] = value; },
    removeAttribute(name) { delete this.attributes[name]; },
  };
  let prevented = false;
  events.submit({ target: form, submitter: { name: 'action', value: 'save', getAttribute: () => null }, defaultPrevented: false,
    preventDefault() { prevented = true; } });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(prevented, true);
  assert.deepEqual(JSON.parse(stored['sh-workspace-tabs-v2']).tabs.map(tab => tab.url), ['/customers/', '/orders/create/']);
  bar.children[1].children[0].onclick();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(content.children.at(-1), unsavedField);
  assert.equal(unsavedField.value, 'customer draft');
});

test('switching tabs does not abort a submitted POST', async () => {
  const { context } = fixture();
  let finishPost;
  let postOptions;
  const originalFetch = context.fetch;
  context.fetch = (url, options) => {
    if (options?.method === 'POST') {
      postOptions = options;
      return new Promise(resolve => { finishPost = () => resolve({ url, headers: { get: () => 'text/html' }, text: async () => String(url) }); });
    }
    return originalFetch(url, options);
  };
  const form = {
    getAttribute(name) { return { method: 'post', action: '/orders/create/' }[name] || null; },
    setAttribute() {}, removeAttribute() {},
  };
  const submission = context.window.SHWorkspace.submitForm(form);
  await context.window.SHWorkspace.openInNewTab('/customers/');
  assert.equal(postOptions.signal, undefined);
  finishPost();
  await submission;
});
