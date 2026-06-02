function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== "") {
        const cookies = document.cookie.split(";");
        for (let i = 0; i < cookies.length; i += 1) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === `${name}=`) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

document.addEventListener("submit", (event) => {
    const form = event.target;
    const message = form.getAttribute("data-confirm");
    if (message && !window.confirm(message)) {
        event.preventDefault();
    }
});

document.addEventListener("click", (event) => {
    const opener = event.target.closest("[data-open-modal]");
    if (opener) {
        const modal = document.getElementById(opener.dataset.openModal);
        if (modal) modal.hidden = false;
    }
    if (event.target.closest("[data-close-modal]")) {
        event.target.closest(".modal").hidden = true;
    }
});
