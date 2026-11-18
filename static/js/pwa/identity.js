// The server supplies these values in the authenticated page shell. Never infer
// identity from a previously downloaded bootstrap or a shared localStorage key.
export function getOfflineScope() {
    const data = document.body?.dataset || {};
    if (!/^\d+$/.test(data.pwaUserId || "")) return null;
    if (data.pwaScope) {
        // Use the same authoritative scope as the server middleware, including
        // "all" for a superuser whose profile happens to have an assigned branch.
        const match = data.pwaScope.match(/^u(\d+)-b(\d+|all)-r([a-z_]+)-s([01])$/);
        return match && match[1] === data.pwaUserId && match[3] === data.pwaRole
            && match[4] === (data.pwaSuperuser === '1' ? '1' : '0') ? data.pwaScope : null;
    }
    const branch = data.pwaBranchId || "all";
    const role = data.pwaRole || "";
    if (!/^(?:\d+|all)$/.test(branch) || !/^[a-z_]+$/.test(role)) return null;
    return `u${data.pwaUserId}-b${branch}-r${role}-s${data.pwaSuperuser === "1" ? "1" : "0"}`;
}

export function databaseName(scope = getOfflineScope()) {
    if (!scope) throw new Error("سجّل الدخول أولًا لتجهيز العمل بدون إنترنت.");
    return `sh-offline-db-${scope}`;
}
