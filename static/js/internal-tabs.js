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
  if (!state || typeof state !== 'object') state = {tabs: []};
  if (!Array.isArray(state.tabs)) state.tabs = [];
  state.tabs = state.tabs.filter(tab => tab && typeof tab.url === 'string' && tab.url.startsWith('/') && !tab.url.startsWith('//') && typeof tab.title === 'string');

  // DOM nodes are moved into these detached containers while their tab is
  // inactive. Moving (instead of serializing) preserves values, selection,
  // event handlers, dynamically added invoice rows, and component state.
  const cache = new Map();
  let activeUrl = currentUrl;
  let lastLoadedUrl = currentUrl;
  let controller = null;
  let navigationNumber = 0;
  let openNextInNewTab = false;
  const shellScriptPattern = /\/static\/js\/(?:main|internal-tabs|table-controls)\.js|\/static\/js\/pwa\//;
  const save = () => {
    state.activeUrl = activeUrl || lastLoadedUrl;
    try { sessionStorage.setItem(storageKey, JSON.stringify(state)); } catch (_error) { /* Private browsing may block storage. */ }
  };
  const titleFor = (doc, url) => doc.querySelector('h1')?.textContent.trim() || doc.title || url;

  function pageMetadata(source = content) {
    return {
      totalRecords: source.hasAttribute('data-total-records') ? source.dataset.totalRecords : null,
      title: document.title,
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
      entry = {holder: document.createElement('div'), metadata: pageMetadata()};
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
    if (entry.metadata?.title) document.title = entry.metadata.title;
    content.removeAttribute('aria-busy');
    activeUrl = url;
    lastLoadedUrl = url;
    if (push) history.pushState({workspace: true}, '', url);
    render();
    document.dispatchEvent(new CustomEvent('sh:page-loaded'));
    requestAnimationFrame(() => window.scrollTo(0, entry.scrollY || 0));
  }

  function render() {
    const previousScrollLeft = bar.scrollLeft;
    bar.innerHTML = '';
    const newTabAction = document.createElement('button');
    newTabAction.type = 'button';
    newTabAction.className = 'workspace-open-next' + (openNextInNewTab ? ' is-armed' : '');
    newTabAction.textContent = openNextInNewTab ? 'اختر الرابط الآن' : '＋ فتح في تبويب جديد';
    newTabAction.setAttribute('aria-pressed', String(openNextInNewTab));
    newTabAction.title = 'اضغط هنا ثم اختر الرابط، أو استخدم Alt مع النقر على الرابط';
    newTabAction.onclick = () => {
      openNextInNewTab = !openNextInNewTab;
      render();
      if (openNextInNewTab) bar.querySelector('.workspace-open-next')?.focus();
    };
    bar.append(newTabAction);
    state.tabs.forEach((tab, index) => {
      const item = document.createElement('div');
      item.className = 'workspace-tab' + (tab.url === activeUrl ? ' active' : '');
      const opener = document.createElement('button');
      opener.type = 'button';
      opener.className = 'workspace-tab-open';
      opener.textContent = tab.title;
      if (tab.url === activeUrl) opener.setAttribute('aria-current', 'page');
      opener.onclick = () => openTab(tab.url, true).catch(handleNavigationError);

      const close = document.createElement('button');
      close.type = 'button';
      close.className = 'workspace-tab-close';
      close.textContent = '×';
      close.setAttribute('aria-label', `إغلاق ${tab.title}`);
      close.onclick = event => {
        event.stopPropagation();
        const page = tab.url === activeUrl ? content : cache.get(tab.url)?.holder;
        if (page?.querySelector('form[data-unsaved="1"]') && !confirm('توجد تغييرات غير محفوظة. هل تريد إغلاق التبويب؟')) return;
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
        if (next) openTab(next.url, true).catch(handleNavigationError);
        else openTab('/', true).catch(handleNavigationError);
      };
      item.onauxclick = event => {
        if (event.button === 1) {
          event.preventDefault();
          close.click();
        }
      };
      item.append(opener, close);
      bar.append(item);
    });
    bar.scrollLeft = previousScrollLeft;
  }

  async function runPageScripts(doc, thisNavigation) {
    for (const script of doc.querySelectorAll('script')) {
      if (thisNavigation !== navigationNumber) return;
      if (script.src) {
        const source = new URL(script.src, location.origin);
        if (shellScriptPattern.test(source.pathname) || source.origin !== location.origin) continue;
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

  async function openTab(value, push = true, replace = false, reuse = false) {
    const url = normalizeUrl(value);
    if (url === activeUrl) return;
    const thisNavigation = ++navigationNumber;
    controller?.abort();

    const previousUrl = activeUrl || lastLoadedUrl;
    const reuseCurrent = reuse && !state.tabs.some(tab => tab.url === url);
    const overwriteCurrent = replace || reuseCurrent;
    if (!overwriteCurrent) stashActivePage();
    if (overwriteCurrent) cache.delete(url);
    const cached = cache.get(url);
    if (cached) {
      restorePage(url, cached, push);
      save();
      return;
    }

    controller = new AbortController();
    const requestController = controller;
    if (!overwriteCurrent) {
      activeUrl = null;
      content.replaceChildren();
      content.setAttribute('aria-busy', 'true');
      const loading = document.createElement('div');
      loading.className = 'card';
      loading.setAttribute('role', 'status');
      loading.textContent = 'جارٍ تحميل التبويب...';
      content.append(loading);
    }

    try {
      const response = await fetch(url, {headers: {'X-Workspace-Tab': '1'}, signal: requestController.signal});
      if (thisNavigation !== navigationNumber) return;
      if (response.redirected && new URL(response.url).pathname.startsWith('/accounts/')) {
        location.href = response.url;
        return;
      }
      if (!response.ok) throw new Error('تعذر تحميل التبويب');
      const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
      if (thisNavigation !== navigationNumber) return;
      const next = doc.querySelector('[data-page-content]');
      if (!next) {
        location.href = url;
        return;
      }

      const previousScrollY = window.scrollY;
      if (overwriteCurrent) stashActivePage();
      content.innerHTML = next.innerHTML;
      const entry = {
        holder: document.createElement('div'),
        metadata: pageMetadata(next),
        scrollY: 0,
      };
      cache.set(url, entry);
      entry.metadata.title = doc.title;
      applyMetadata(entry.metadata);
      content.removeAttribute('aria-busy');
      if (overwriteCurrent) {
        cache.delete(previousUrl);
        state.tabs = state.tabs.filter(tab => tab.url !== previousUrl);
        if (replace) history.replaceState({workspace: true}, '', url);
      }
      ensureTab(url, titleFor(doc, url));
      activeUrl = url;
      lastLoadedUrl = url;
      if (push) history.pushState({workspace: true}, '', url);
      document.title = doc.title || document.title;
      await runPageScripts(doc, thisNavigation);
      if (thisNavigation !== navigationNumber) return;
      save();
      render();
      document.dispatchEvent(new CustomEvent('sh:page-loaded'));
      window.scrollTo(0, replace ? previousScrollY : 0);
    } catch (error) {
      if (error.name === 'AbortError' || thisNavigation !== navigationNumber) return;
      cache.delete(url);
      content.removeAttribute('aria-busy');
      if (overwriteCurrent) throw error;
      activeUrl = null;
      const previous = previousUrl && cache.get(previousUrl);
      if (previous) {
        history.replaceState({workspace: true}, '', previousUrl);
        restorePage(previousUrl, previous, false);
      }
      throw error;
    }
  }

  function handleNavigationError(error) {
    if (error.name === 'AbortError') return;
    if (typeof showPwaNotice === 'function') showPwaNotice('تعذر تحميل الصفحة. تحقق من الاتصال وحاول مرة أخرى.', true);
    else alert('تعذر تحميل الصفحة. تحقق من الاتصال وحاول مرة أخرى.');
  }
  window.SHWorkspace = {
    hasUnsavedChanges: () => [...cache.values()].some(entry => entry.holder.querySelector('form[data-unsaved="1"]')),
    navigate: url => openTab(url, true, false, true),
    openInNewTab: url => openTab(url, true),
    navigateFilter: url => openTab(url, false, true),
  };

  document.addEventListener('click', event => {
    const link = event.target.closest('a[href]');
    if (!link || event.defaultPrevented || event.button !== 0 || link.target || link.hasAttribute('download') || event.ctrlKey || event.metaKey || event.shiftKey) return;
    const url = new URL(link.href, location.origin);
    if (url.hash && normalizeUrl(url.href) === activeUrl) return;
    if (/\.(pdf|xlsx?|csv)$/i.test(url.pathname) || url.pathname.includes('/export/') || url.pathname.includes('/print')) return;
    if (url.pathname.includes('/logout')) { try { sessionStorage.removeItem(storageKey); } catch (_error) { /* Storage unavailable. */ } }
    if (url.origin !== location.origin || url.pathname.startsWith('/accounts/') || url.pathname.startsWith('/admin/')) return;
    event.preventDefault();
    const newTab = openNextInNewTab || event.altKey;
    if (!newTab && !state.tabs.some(tab => tab.url === normalizeUrl(url.href)) && content.querySelector('form[data-unsaved="1"]') &&
        !confirm('توجد تغييرات غير محفوظة. هل تريد الانتقال إلى الصفحة الأخرى؟')) return;
    if (openNextInNewTab) {
      openNextInNewTab = false;
      render();
    }
    openTab(url.pathname + url.search, true, false, !newTab).catch(error => {
      if (error.name !== 'AbortError') {
        alert('تعذر تحميل الصفحة. سيتم فتحها بالطريقة العادية.');
        location.href = url.href;
      }
    });
  });

  addEventListener('popstate', () => openTab(location.pathname + location.search, false, false, true).catch(handleNavigationError));

  cache.set(currentUrl, {
    holder: document.createElement('div'),
    metadata: pageMetadata(),
    scrollY: window.scrollY,
  });
  if (!state.tabs.some(tab => tab.url === currentUrl)) {
    const previousTab = state.tabs.find(tab => tab.url === state.activeUrl);
    if (previousTab) {
      previousTab.url = currentUrl;
      previousTab.title = document.querySelector('h1')?.textContent.trim() || document.title;
    }
  }
  ensureTab(currentUrl, document.querySelector('h1')?.textContent.trim() || document.title);
  save();
  render();
})();
