(() => {
    const form = document.getElementById('bulk-transfer-form');
    if (!form) return;
    const total = form.elements['items-TOTAL_FORMS'];
    const button = document.getElementById('add-transfer-line');
    button.addEventListener('click', () => {
        const index = Number(total.value);
        if (index >= 100) return;
        const html = document.getElementById('transfer-empty-line').innerHTML.replaceAll('__prefix__', index);
        document.getElementById('transfer-lines').insertAdjacentHTML('beforeend', html);
        total.value = index + 1;
        button.disabled = index + 1 >= 100;
    });
})();
