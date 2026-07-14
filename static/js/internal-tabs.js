(function () {
  const bar = document.querySelector('[data-workspace-tabs]');
  const content = document.querySelector('[data-page-content]');
  if (!bar || !content) return;

  const storageKey = 'sh-workspace-tabs-v2';
  const normalizeUrl = value => {
    const url = new URL(value, location.origin);
    return url.pathname + url.search;
  };
  const currentUrl = normalizeUrl(location.href);
  let state;
  try {
    state = JSON.parse(sessionStorage.getItem(storageKey) || '{"tabs":[]}');
  } catch (_error) {
    state = {tabs: []};
  }
  if (!Array.isArray(state.tabs)) state.tabs = [];

  // DOM nodes are moved into these detached containers while their tab is
  // inactive. Moving (instead of serializing) preserves values, selection,
  // event handlers, dynamically added invoice rows, and component state.
  const cache = new Map();
  let activeUrl = currentUrl;
  let controller = null;
  const shellScriptPattern = /\/static\/js\/(?:main|internal-tabs)\.js|\/static\/js\/pwa\//;
  const save = () => sessionStorage.setItem(storageKey, JSON.stringify(state));
  const titleFor = (doc, url) => doc.querySelector('h1')?.textContent.trim() || doc.title || url;

  function pageMetadata(source = content) {
    return {
      totalRecords: source.hasAttribute('data-total-records') ? source.dataset.totalRecords : null,
    };
  }

  function applyMetadata(metadata) {
    if (metadata?.totalRecords !== null && metadata?.totalRecords !== undefined) {
      content.dataset.totalRecords = metadata.totalRecords;
    } else {
      delete content.dataset.totalRecords;
    }
  }

  function ensureTab(url, title) {
    let tab = state.tabs.find(item => item.url === url);
    if (!tab) {
      tab = {url, title};
      state.tabs.push(tab);
    } else if (title) {
      tab.title = title;
    }
    return tab;
  }

  function stashActivePage() {
    if (!activeUrl) return;
    let entry = cache.get(activeUrl);
    if (!entry) {
      entry = {holder: document.createElement('div'), dirty: false, metadata: pageMetadata()};
      cache.set(activeUrl, entry);
    }
    entry.metadata = pageMetadata();
    entry.scrollY = window.scrollY;
    while (content.firstChild) entry.holder.appendChild(content.firstChild);
  }

  function restorePage(url, entry, push) {
    content.replaceChildren();
    while (entry.holder.firstChild) content.appendChild(entry.holder.firstChild);
    applyMetadata(entry.metadata);
    content.removeAttribute('aria-busy');
    activeUrl = url;
    if (push) history.pushState({workspace: true}, '', url);
    render();
    requestAnimationFrame(() => window.scrollTo(0, entry.scrollY || 0));
  }

  function render() {
    bar.innerHTML = '';
    state.tabs.forEach((tab, index) => {
      const item = document.createElement('button');
      item.type = 'button';
      item.className = 'workspace-tab' + (tab.url === activeUrl ? ' active' : '');
      item.append(document.createTextNode(tab.title));
      item.onclick = () => openTab(tab.url, true);

      const close = document.createElement('span');
      close.textContent = ' ×';
      close.setAttribute('aria-label', 'إغلاق');
      close.onclick = event => {
        event.stopPropagation();
        const entry = cache.get(tab.url);
        if (entry?.dirty && !confirm('يوجد نموذج غير محفوظ. هل تريد إغلاق التبويب؟')) return;
        state.tabs.splice(index, 1);
        cache.delete(tab.url);
        save();
        if (tab.url !== activeUrl) {
          render();
          return;
        }
        content.replaceChildren();
        activeUrl = null;
        const next = state.tabs[Math.max(0, index - 1)];
        if (next) openTab(next.url, true);
        else openTab('/', true);
      };
      item.onauxclick = event => {
        if (event.button === 1) {
          event.preventDefault();
          close.click();
        }
      };
      item.append(close);
      bar.append(item);
    });
  }

  async function runPageScripts(doc) {
    for (const script of doc.querySelectorAll('script')) {
      if (script.src) {
        const source = new URL(script.src, location.origin);
        if (shellScriptPattern.test(source.pathname)) continue;
        await new Promise((resolve, reject) => {
          const loaded = document.createElement('script');
          loaded.src = source.href;
          if (script.type) loaded.type = script.type;
          loaded.onload = () => { loaded.remove(); resolve(); };
          loaded.onerror = () => { loaded.remove(); reject(new Error(`تعذر تحميل ${source.pathname}`)); };
          document.body.appendChild(loaded);
        });
      } else if ((!script.type || script.type === 'text/javascript' || script.type === 'module') && script.textContent.trim()) {
        const inline = document.createElement('script');
        if (script.type) inline.type = script.type;
        inline.textContent = script.textContent;
        document.body.appendChild(inline);
        inline.remove();
      }
    }
  }

  async function openTab(value, push = true) {
    const url = normalizeUrl(value);
    if (url === activeUrl) return;

    const previousUrl = activeUrl;
    stashActivePage();
    const cached = cache.get(url);
    if (cached) {
      restorePage(url, cached, push);
      save();
      return;
    }

    controller?.abort();
    controller = new AbortController();
    activeUrl = null;
    content.replaceChildren();
    content.setAttribute('aria-busy', 'true');
    const loading = document.createElement('div');
    loading.className = 'card';
    loading.textContent = 'جارٍ تحميل التبويب...';
    content.append(loading);

    try {
      const response = await fetch(url, {headers: {'X-Workspace-Tab': '1'}, signal: controller.signal});
      if (response.redirected && new URL(response.url).pathname.startsWith('/accounts/')) {
        location.href = response.url;
        return;
      }
      if (!response.ok) throw new Error('تعذر تحميل التبويب');
      const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
      const next = doc.querySelector('[data-page-content]');
      if (!next) {
        location.href = url;
        return;
      }

      content.innerHTML = next.innerHTML;
      const entry = {
        holder: document.createElement('div'),
        dirty: false,
        metadata: pageMetadata(next),
        scrollY: 0,
      };
      cache.set(url, entry);
      applyMetadata(entry.metadata);
      content.removeAttribute('aria-busy');
      ensureTab(url, titleFor(doc, url));
      activeUrl = url;
      await runPageScripts(doc);
      if (push) history.pushState({workspace: true}, '', url);
      save();
      render();
      document.dispatchEvent(new CustomEvent('sh:page-loaded'));
      window.scrollTo(0, 0);
    } catch (error) {
      if (error.name === 'AbortError') return;
      cache.delete(url);
      content.removeAttribute('aria-busy');
      activeUrl = null;
      const previous = previousUrl && cache.get(previousUrl);
      if (previous) restorePage(previousUrl, previous, false);
      throw error;
    }
  }

  document.addEventListener('click', event => {
    const link = event.target.closest('a[href]');
    if (!link || link.target || link.hasAttribute('download') || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const url = new URL(link.href, location.origin);
    if (url.hash && normalizeUrl(url.href) === activeUrl) return;
    if (/\.(pdf|xlsx?|csv)$/i.test(url.pathname) || url.pathname.includes('/export/') || url.pathname.includes('/print')) return;
    if (url.pathname.includes('/logout')) sessionStorage.removeItem(storageKey);
    if (url.origin !== location.origin || url.pathname.startsWith('/accounts/') || url.pathname.startsWith('/admin/')) return;
    event.preventDefault();
    openTab(url.pathname + url.search).catch(error => {
      if (error.name !== 'AbortError') {
        alert('تعذر تحميل الصفحة. سيتم فتحها بالطريقة العادية.');
        location.href = url.href;
      }
    });
  });

  const markActiveFormDirty = event => {
    if (!event.target.closest('form') || !activeUrl) return;
    const entry = cache.get(activeUrl);
    if (entry) entry.dirty = true;
  };
  document.addEventListener('input', markActiveFormDirty);
  document.addEventListener('change', markActiveFormDirty);
  document.addEventListener('submit', () => {
    const entry = activeUrl && cache.get(activeUrl);
    if (entry) entry.dirty = false;
  });
  addEventListener('popstate', () => openTab(location.pathname + location.search, false));
  addEventListener('beforeunload', event => {
    if ([...cache.values()].some(entry => entry.dirty)) {
      event.preventDefault();
      event.returnValue = '';
    }
  });

  cache.set(currentUrl, {
    holder: document.createElement('div'),
    dirty: false,
    metadata: pageMetadata(),
    scrollY: window.scrollY,
  });
  ensureTab(currentUrl, document.querySelector('h1')?.textContent.trim() || document.title);
  save();
  render();
})();
