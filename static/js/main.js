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

function openModal(modal) {
    if (!modal) return;
    modal.hidden = false;
    document.body.classList.add("modal-open");
    const firstField = modal.querySelector("input, select, textarea, button, a[href]");
    firstField?.focus({ preventScroll: true });
}

function closeModal(modal) {
    if (!modal) return;
    modal.hidden = true;
    if (!document.querySelector(".modal:not([hidden])")) {
        document.body.classList.remove("modal-open");
    }
}

document.addEventListener("click", (event) => {
    const opener = event.target.closest("[data-open-modal]");
    if (opener) {
        openModal(document.getElementById(opener.dataset.openModal));
    }

    const closeButton = event.target.closest("[data-close-modal]");
    if (closeButton) {
        closeModal(closeButton.closest(".modal"));
    }

    if (event.target.classList?.contains("modal")) {
        closeModal(event.target);
    }
});

document.addEventListener("DOMContentLoaded", () => {
    const currentPath = window.location.pathname;
    document.querySelectorAll(".side-nav a").forEach((link) => {
        const linkPath = new URL(link.href, window.location.origin).pathname;
        if (linkPath === currentPath || (linkPath !== "/" && currentPath.startsWith(linkPath))) {
            link.classList.add("is-active");
            const group = link.closest(".nav-group");
            if (group) {
                group.classList.add("is-open", "is-active");
                group.querySelector(".nav-group-toggle")?.setAttribute("aria-expanded", "true");
            }
        }
    });

    const hasOpenGroup = document.querySelector(".nav-group.is-open");
    if (!hasOpenGroup) {
        const firstGroup = document.querySelector(".nav-group");
        firstGroup?.classList.add("is-open");
        firstGroup?.querySelector(".nav-group-toggle")?.setAttribute("aria-expanded", "true");
    }
});

document.addEventListener("click", (event) => {
    const groupToggle = event.target.closest("[data-nav-group-toggle]");
    if (groupToggle) {
        event.preventDefault();
        event.stopPropagation();
        const group = groupToggle.closest(".nav-group");
        if (!group) return;
        const isOpen = !group.classList.contains("is-open");
        group.classList.toggle("is-open", isOpen);
        groupToggle.setAttribute("aria-expanded", String(isOpen));
        return;
    }

    if (event.target.closest("[data-sidebar-toggle]")) {
        document.body.classList.toggle("sidebar-open");
    }

    if (event.target.closest("[data-sidebar-close]") || event.target.closest(".side-nav a")) {
        document.body.classList.remove("sidebar-open");
    }
});

document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    closeModal(document.querySelector(".modal:not([hidden])"));
    document.body.classList.remove("sidebar-open");
});
