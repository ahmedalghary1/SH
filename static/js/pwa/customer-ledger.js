import { calculateOrderTotals } from './db.js';

const cents = value => Math.round(Number(value || 0) * 100);
const money = value => (value / 100).toFixed(2);

export function localCustomerStatement(customer, sales, payments) {
    const snapshot = customer.statement_snapshot;
    if (!snapshot) throw new Error('لم يُنزّل كشف هذا العميل بعد. اتصل بالإنترنت وأكمل تنزيل البيانات.');
    const entries = snapshot.entries.map(entry => ({ ...entry }));
    const orderIds = new Set(entries.filter(entry => entry.order_id).map(entry => String(entry.order_id)));
    const paymentIds = new Set([
        ...(snapshot.payment_ids || []).map(String),
        ...entries.filter(entry => entry.payment_id).map(entry => String(entry.payment_id)),
    ]);
    const customerId = String(customer.server_id || customer.id);
    const belongs = data => String(data.customer_server_id || data.customer || '') === customerId;
    const local = [];
    for (const sale of sales) {
        const order = sale.order;
        if (!order || !belongs(order) || order.document_type === 'quote'
            || order.action !== 'confirm' || orderIds.has(String(sale.server_id))) continue;
        const total = calculateOrderTotals({ ...order, items: sale.items || [] }).total;
        local.push({ date: (sale.created_at || sale.updated_at).slice(0, 10), type: 'بيع محلي',
            debit: total, credit: order.paid_amount || '0', local: true });
    }
    for (const payment of payments) {
        const data = payment.payment || payment.form;
        if (!data || !belongs(data) || paymentIds.has(String(payment.server_id))) continue;
        if (payment.original_url !== '/finance/transactions/collection/'
            && !/^\/invoices\/\d+\/payments\/add\/$/.test(payment.original_url || '')) continue;
        local.push({ date: String(data.transaction_date || payment.created_at || payment.updated_at).slice(0, 10),
            type: 'قبض محلي', debit: '0', credit: data.amount || '0', local: true });
    }
    // Keep the downloaded ledger order (including opening entries) intact.
    // Pending work is provisional and shown after the downloaded statement.
    let balance = entries.length ? cents(entries[entries.length - 1].balance) : 0;
    for (const entry of local) {
        balance += cents(entry.debit) - cents(entry.credit);
        entries.push({ ...entry, balance: money(balance) });
    }
    return { entries, balance: money(balance), downloaded_at: snapshot.downloaded_at };
}
