(function () {
  const bar = document.querySelector('[data-workspace-tabs]');
  const content = document.querySelector('[data-page-content]');
  if (!bar || !content) return;
  const key = 'sh-workspace-tabs-v1';
  let dirty = false;
  let activeUrl = location.pathname + location.search;
  let controller = null;
  const state = JSON.parse(sessionStorage.getItem(key) || '{"tabs":[]}');
  const save = () => sessionStorage.setItem(key, JSON.stringify(state));
  const titleFor = (doc, url) => doc.querySelector('h1')?.textContent.trim() || doc.title || url;

  function render() {
    bar.innerHTML = '';
    state.tabs.forEach((tab, index) => {
      const item = document.createElement('button');
      item.type = 'button'; item.className = 'workspace-tab' + (tab.url === location.pathname + location.search ? ' active' : '');
      item.textContent = tab.title;
      item.onclick = () => open(tab.url, false);
      const close = document.createElement('span'); close.textContent = ' ×'; close.setAttribute('aria-label', 'إغلاق');
      close.onclick = (event) => {
        event.stopPropagation();
        if (tab.url === activeUrl && dirty && !confirm('يوجد نموذج غير محفوظ. هل تريد إغلاق التبويب؟')) return;
        state.tabs.splice(index, 1); save();
        if (tab.url === activeUrl) {
          const next = state.tabs[Math.max(0, index - 1)];
          if (next) open(next.url); else open('/');
        } else render();
      };
      item.onauxclick = event => { if (event.button === 1) { event.preventDefault(); close.click(); } };
      item.append(close); bar.append(item);
    });
  }

  async function open(url, push = true) {
    if (dirty && !confirm('يوجد نموذج غير محفوظ. هل تريد مغادرة الصفحة؟')) return;
    controller?.abort(); controller = new AbortController();
    content.setAttribute('aria-busy', 'true');
    const loading = document.createElement('div'); loading.className = 'card'; loading.textContent = 'جارٍ تحميل التبويب...'; content.prepend(loading);
    const response = await fetch(url, {headers: {'X-Workspace-Tab': '1'}, signal: controller.signal});
    if (response.redirected && new URL(response.url).pathname.startsWith('/accounts/')) { location.href = response.url; return; }
    if (!response.ok) throw new Error('تعذر تحميل التبويب');
    const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
    const next = doc.querySelector('[data-page-content]');
    if (!next) { location.href = url; return; }
    content.innerHTML = next.innerHTML;
    content.removeAttribute('aria-busy');
    for (const script of doc.querySelectorAll('script')) {
      if (script.src && !document.querySelector(`script[src="${script.getAttribute('src')}"]`)) {
        const loaded = document.createElement('script'); loaded.src = script.src; if (script.type) loaded.type = script.type; document.body.append(loaded);
      } else if (!script.src && script.textContent.trim()) {
        const inline = document.createElement('script'); inline.textContent = script.textContent; document.body.append(inline); inline.remove();
      }
    }
    const normalized = new URL(url, location.origin).pathname + new URL(url, location.origin).search;
    const found = state.tabs.find(tab => tab.url === normalized);
    if (found) found.title = titleFor(doc, normalized); else state.tabs.push({url: normalized, title: titleFor(doc, normalized)});
    activeUrl = normalized; dirty = false; save(); if (push) history.pushState({workspace: true}, '', normalized); render();
    document.dispatchEvent(new CustomEvent('sh:page-loaded'));
  }

  document.addEventListener('click', event => {
    const link = event.target.closest('a[href]');
    if (!link || link.target || link.hasAttribute('download') || event.ctrlKey || event.metaKey || event.shiftKey) return;
    const url = new URL(link.href, location.origin);
    if (/\.(pdf|xlsx?|csv)$/i.test(url.pathname) || url.pathname.includes('/export/') || url.pathname.includes('/print')) return;
    if (url.pathname.includes('/logout')) sessionStorage.removeItem(key);
    if (url.origin !== location.origin || url.pathname.startsWith('/accounts/') || url.pathname.startsWith('/admin/')) return;
    event.preventDefault(); open(url.pathname + url.search).catch(error => { if (error.name !== 'AbortError') { alert('تعذر تحميل الصفحة. سيتم فتحها بالطريقة العادية.'); location.href = url.href; } });
  });
  document.addEventListener('input', event => { if (event.target.closest('form')) dirty = true; });
  document.addEventListener('submit', () => { dirty = false; });
  addEventListener('popstate', () => open(location.pathname + location.search, false));
  addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
  const current = location.pathname + location.search;
  if (!state.tabs.some(tab => tab.url === current)) state.tabs.push({url: current, title: document.querySelector('h1')?.textContent.trim() || document.title});
  save(); render();
})();
