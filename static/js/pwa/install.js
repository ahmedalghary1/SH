// A browser accepting a prompt is not proof that the OS installed an app.
// Keep this independent of authenticated data and of the synchronization queue.
(() => {
    const storageKey = 'sh-pwa-installed-v1';
    const modes = ['standalone', 'minimal-ui', 'window-controls-overlay', 'fullscreen']
        .map(mode => window.matchMedia?.(`(display-mode: ${mode})`)).filter(Boolean);
    const standalone = () => navigator.standalone === true || modes.some(mode => mode.matches);
    let promptEvent = null;
    let busy = false;
    let revision = 0;
    let confirmed = false;
    try { confirmed = Boolean(window.localStorage.getItem(storageKey)); } catch { /* Storage may be disabled. */ }

    function render() {
        document.querySelectorAll('[data-pwa-install]').forEach(button => {
            button.hidden = confirmed || standalone() || !promptEvent || busy;
            button.disabled = busy;
        });
    }

    function markInstalled() {
        revision += 1;
        confirmed = true;
        promptEvent = null;
        try { window.localStorage.setItem(storageKey, String(Date.now())); } catch { /* Detection still works in this tab. */ }
        render();
    }

    async function installedRelatedApp() {
        if (!navigator.getInstalledRelatedApps) return false;
        try {
            const apps = await navigator.getInstalledRelatedApps();
            return apps.some(app => app.platform === 'webapp' && (
                (app.id && new URL(app.id, window.location.origin).href === new URL('/', window.location.origin).href)
                || (app.url && new URL(app.url, window.location.origin).href === new URL('/manifest.json', window.location.origin).href)
            ));
        } catch { return false; }
    }

    async function refresh() {
        if (standalone()) { markInstalled(); return; }
        const current = revision;
        if (await installedRelatedApp() && current === revision) markInstalled();
        render();
    }

    window.addEventListener('beforeinstallprompt', async event => {
        event.preventDefault();
        const current = ++revision;
        if (standalone()) { markInstalled(); return; }
        if (await installedRelatedApp()) {
            if (current === revision) markInstalled();
            return;
        }
        if (current !== revision) return;
        // A fresh browser eligibility event permits reinstall after uninstall.
        // A remembered install flag alone must never permanently block it.
        confirmed = false;
        try { window.localStorage.removeItem(storageKey); } catch { /* Optional cross-tab hint. */ }
        promptEvent = event;
        render();
    });

    document.addEventListener('click', async event => {
        if (!event.target.closest('[data-pwa-install]') || !promptEvent || busy || confirmed || standalone()) return;
        const candidate = promptEvent;
        promptEvent = null; // A native prompt is single-use, including rejection.
        busy = true;
        render();
        try {
            // Invoke before awaiting anything, while the click still grants activation.
            await candidate.prompt();
            const choice = await candidate.userChoice;
            if (choice.outcome === 'accepted' && !confirmed) {
                window.showPwaNotice?.('تم قبول طلب التثبيت. انتظر اكتماله في المتصفح؛ إذا لم يظهر SH فراجع قائمة التطبيقات في Chrome أو Edge.');
            }
        } catch (error) {
            console.warn('PWA installation prompt failed', error);
            window.showPwaNotice?.('تعذر إكمال التثبيت. جرّب خيار تثبيت التطبيق من قائمة Chrome أو Edge باستخدام رابط HTTPS نفسه.', true);
        } finally {
            busy = false;
            render();
        }
    });

    window.addEventListener('appinstalled', () => {
        markInstalled();
        window.showPwaNotice?.('اكتمل تثبيت SH في هذا المتصفح. افتحه من قائمة التطبيقات أو قائمة ابدأ.');
        Promise.resolve().then(() => window.SHSync?.processQueue?.())
            .then(() => window.SHSync?.bootstrapNow?.())
            .then(() => window.SHSync?.cacheAppShell?.())
            .catch(error => console.warn('Installed app offline preparation failed', error));
    });
    window.addEventListener('storage', event => {
        if (event.key !== storageKey) return;
        if (event.newValue) { confirmed = true; promptEvent = null; revision += 1; }
        else confirmed = false;
        render();
    });
    window.addEventListener('focus', refresh);
    window.addEventListener('pageshow', refresh);
    document.addEventListener('sh:page-loaded', render);
    modes.forEach(mode => mode.addEventListener?.('change', refresh));
    render();
    refresh();
})();
