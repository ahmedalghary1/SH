(() => {
    const picker = document.querySelector('[data-customer-picker]');
    if (!picker) return;

    const search = picker.querySelector('#statement-customer-search');
    const customerId = picker.querySelector('#statement-customer-id');
    const results = picker.querySelector('#statement-customer-results');
    const searchUrl = picker.dataset.searchUrl;
    let timer;
    let controller;

    function closeResults() {
        results.hidden = true;
        results.replaceChildren();
        search.setAttribute('aria-expanded', 'false');
    }

    function showMessage(message) {
        const paragraph = document.createElement('p');
        paragraph.textContent = message;
        results.replaceChildren(paragraph);
        results.hidden = false;
        search.setAttribute('aria-expanded', 'true');
    }

    search.addEventListener('input', () => {
        clearTimeout(timer);
        controller?.abort();
        customerId.value = '';
        const query = search.value.trim();
        if (query.length < 2) {
            closeResults();
            return;
        }

        timer = setTimeout(async () => {
            controller = new AbortController();
            try {
                const url = new URL(searchUrl, window.location.href);
                url.searchParams.set('q', query);
                const response = await fetch(url, {
                    signal: controller.signal,
                    headers: { 'X-Requested-With': 'XMLHttpRequest' },
                });
                if (!response.ok) throw new Error('Search failed');
                const payload = await response.json();
                if (search.value.trim() !== query) return;
                const customers = payload.data || [];
                if (!customers.length) {
                    showMessage('لا توجد نتائج مطابقة.');
                    return;
                }
                results.replaceChildren();
                customers.forEach((customer) => {
                    const option = document.createElement('button');
                    option.type = 'button';
                    const name = document.createElement('strong');
                    name.textContent = customer.name;
                    const info = document.createElement('small');
                    info.textContent = customer.phone || `#${customer.id}`;
                    option.append(name, info);
                    option.addEventListener('click', () => {
                        search.value = customer.name;
                        customerId.value = customer.id;
                        closeResults();
                        picker.querySelector('button[type="submit"]').focus();
                    });
                    results.append(option);
                });
                results.hidden = false;
                search.setAttribute('aria-expanded', 'true');
            } catch (error) {
                if (error.name !== 'AbortError') showMessage('تعذر البحث الآن. أدخل رقم العميل مباشرة.');
            }
        }, 250);
    });

    search.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') closeResults();
        if (event.key === 'Enter' && !results.hidden) {
            const first = results.querySelector('button');
            if (first) {
                event.preventDefault();
                first.click();
            }
        }
    });
    customerId.addEventListener('input', () => {
        if (customerId.value) {
            search.value = '';
            closeResults();
        }
    });
    document.addEventListener('click', (event) => {
        if (!picker.contains(event.target)) closeResults();
    });
})();
