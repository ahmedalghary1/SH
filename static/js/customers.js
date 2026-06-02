function bindB2BFields() {
    const type = document.getElementById("id_customer_type");
    if (!type) return;
    const company = document.getElementById("id_company_name")?.closest("label");
    const tax = document.getElementById("id_tax_number")?.closest("label");
    const update = () => {
        const show = type.value === "b2b";
        if (company) company.style.display = show ? "" : "none";
        if (tax) tax.style.display = show ? "" : "none";
    };
    type.addEventListener("change", update);
    update();
}
document.addEventListener("DOMContentLoaded", bindB2BFields);
