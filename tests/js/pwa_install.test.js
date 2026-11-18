const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { test } = require('node:test');
const source = fs.readFileSync('static/js/pwa/install.js', 'utf8');

function fixture({ installed = [], standalone = false, storage = new Map(), blockedStorage = false } = {}) {
    const events = {}, documentEvents = {}, notices = [];
    const buttons = [{ hidden: true }, { hidden: true }];
    const media = [];
    const navigator = { getInstalledRelatedApps: async () => installed };
    const window = {
        location: { origin: 'https://erp.test' },
        localStorage: {
            getItem: key => { if (blockedStorage) throw Error('blocked'); return storage.get(key); },
            setItem: (key, value) => { if (blockedStorage) throw Error('blocked'); storage.set(key, value); },
            removeItem: key => { if (blockedStorage) throw Error('blocked'); storage.delete(key); },
        },
        matchMedia: query => {
            const value = { matches: standalone && query.includes('standalone'), addEventListener(_type, fn) { this.change = fn; } };
            media.push(value);
            return value;
        },
        addEventListener: (type, fn) => { events[type] = fn; },
        showPwaNotice: (...args) => notices.push(args),
    };
    const document = {
        querySelectorAll: () => buttons,
        addEventListener: (type, fn) => { documentEvents[type] = fn; },
    };
    vm.runInNewContext(source, { window, document, navigator, URL, Date, Promise, console: { warn() {} } });
    return { buttons, events, navigator, storage, notices, media,
        click: () => documentEvents.click({target: {closest: () => buttons[0]}}),
        async offer(overrides = {}) {
            const prompt = { preventDefault() {}, prompt: async () => {}, userChoice: Promise.resolve({ outcome: 'dismissed' }), ...overrides };
            await events.beforeinstallprompt(prompt);
            return prompt;
        },
    };
}

test('installed related app and standalone launches hide installation in every tab', async () => {
    const storage = new Map();
    const app = fixture({ standalone: true, storage });
    await app.offer();
    assert.ok(app.buttons.every(button => button.hidden));
    const tab = fixture({ storage, installed: [{platform: 'webapp', id: 'https://erp.test/'}] });
    await tab.offer();
    assert.ok(tab.buttons.every(button => button.hidden));
    assert.ok(storage.has('sh-pwa-installed-v1'));
});

test('accepting a native prompt does not record a successful installation', async () => {
    const f = fixture();
    let calls = 0, resolve;
    const choice = new Promise(done => { resolve = done; });
    await f.offer({ prompt: () => { calls++; return Promise.resolve(); }, userChoice: choice });
    assert.ok(f.buttons.every(button => !button.hidden));
    const click = f.click();
    assert.equal(calls, 1); // Native prompt is invoked synchronously in the click.
    await f.click();
    assert.equal(calls, 1);
    resolve({ outcome: 'accepted' });
    await click;
    assert.equal(f.storage.size, 0);
    assert.ok(f.buttons.every(button => button.hidden && !button.disabled));
    await f.events.appinstalled();
    assert.ok(f.storage.has('sh-pwa-installed-v1'));
});

test('installation is broadcast across tabs and persists through a new tab', async () => {
    const storage = new Map();
    const first = fixture({storage}), second = fixture({storage});
    await second.offer();
    first.events.appinstalled();
    second.events.storage({key: 'sh-pwa-installed-v1', newValue: storage.get('sh-pwa-installed-v1')});
    assert.ok(second.buttons.every(button => button.hidden));
    const third = fixture({storage});
    assert.ok(third.buttons.every(button => button.hidden));
});

test('a fresh eligibility event permits reinstall without trusting an old local flag', async () => {
    const f = fixture({storage: new Map([['sh-pwa-installed-v1', 'old-install']])});
    await f.offer();
    assert.ok(f.buttons.every(button => !button.hidden));
    assert.equal(f.storage.size, 0);
});

test('prompt rejection, dismissal and blocked storage remain recoverable', async () => {
    const f = fixture({blockedStorage: true});
    await f.offer({ prompt: () => Promise.reject(Error('OS declined')) });
    await f.click();
    assert.equal(f.notices.at(-1)[1], true);
    assert.ok(f.buttons.every(button => button.hidden && !button.disabled));
    await f.offer();
    await f.click();
    await f.offer();
    assert.ok(f.buttons.every(button => !button.hidden));
    f.events.appinstalled();
    assert.ok(f.buttons.every(button => button.hidden));
});

test('focus while checking eligibility does not lose the native event', async () => {
    const f = fixture();
    let resolve;
    f.navigator.getInstalledRelatedApps = () => new Promise(done => { resolve = done; });
    const offered = f.offer();
    const finishOffer = resolve;
    const focused = f.events.focus();
    finishOffer([]);
    await offered;
    resolve([]);
    await focused;
    assert.ok(f.buttons.every(button => !button.hidden));
});

test('confirmation during a slow eligibility check wins over an outdated result', async () => {
    const f = fixture();
    let resolve;
    f.navigator.getInstalledRelatedApps = () => new Promise(done => { resolve = done; });
    const offered = f.offer();
    f.events.storage({key: 'sh-pwa-installed-v1', newValue: 'confirmed'});
    resolve([]);
    await offered;
    assert.ok(f.buttons.every(button => button.hidden));
});
