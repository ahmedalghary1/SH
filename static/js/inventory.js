(function () {
    // main.js owns the shared stock component so every page and workspace tab
    // uses the same validation and protection against stale responses.
    if (typeof setupStockWarehouseFilters === "function") setupStockWarehouseFilters();
})();
