const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { test } = require('node:test');
const source = fs.readFileSync('static/js/pwa/offline-forms.js', 'utf8');
function helpers() {
    const context = vm.createContext({});
    for (const name of ['positiveStockQuantity','stockMutationsForSubmission']) {
        vm.runInContext(source.match(new RegExp(`function ${name}\\([^]*?\\n\\}`))[0], context);
    }
    return context;
}
function sale(quantity=2, extra={}) {
    return {order:{action:'confirm',warehouse:7,...extra},items:[{variant_server_id:4,quantity}]};
}
test('confirmed sale uses server variant ids and the default warehouse; quotes and drafts reserve nothing', () => {
    const h=helpers();
    const mutations=h.stockMutationsForSubmission({entity_name:'sales'},sale());
    assert.equal(mutations[0].variant_id,4);
    assert.equal(mutations[0].warehouse_id,7);
    assert.equal(mutations[0].delta,-2);
    assert.equal(h.stockMutationsForSubmission({entity_name:'sales'},sale(2,{document_type:'quote'})).length,0);
    assert.equal(h.stockMutationsForSubmission({entity_name:'sales'},sale(2,{action:'new_invoice'})).length,0);
    for (const quantity of [-2,0,1.5,'bad']) {
        assert.throws(()=>h.stockMutationsForSubmission({entity_name:'sales'},sale(quantity)));
    }
});
test('bulk transfer includes every line, skips deleted and blank rows and preserves both warehouse effects', () => {
    const h=helpers();
    const payload={original_url:'/inventory/movements/transfer/',stock:{from_warehouse:1,to_warehouse:2,
        'items-TOTAL_FORMS':'4','items-0-variant':3,'items-0-quantity':'2',
        'items-1-variant':4,'items-1-quantity':'5','items-2-DELETE':'on'}};
    const mutations=h.stockMutationsForSubmission({entity_name:'stock'},payload);
    assert.deepEqual(Array.from(mutations,m=>[m.variant_id,m.warehouse_id,m.delta]),[[3,1,-2],[3,2,2],[4,1,-5],[4,2,5]]);
    payload.stock.to_warehouse=1;
    assert.throws(()=>h.stockMutationsForSubmission({entity_name:'stock'},payload));
});

test('local invoice totals include item discounts, invoice discounts and remaining payment', () => {
    const dbSource = fs.readFileSync('static/js/pwa/db.js', 'utf8');
    const declaration = dbSource.match(/export function calculateOrderTotals\([^]*?\n\}/)[0].replace('export ', '');
    const context = vm.createContext({});
    vm.runInContext(declaration, context);
    const totals = context.calculateOrderTotals({
        items: [{quantity:2, unit_price:100, discount_amount:10, discount_percentage:5}],
        discount_amount:10, discount_percentage:10, paid_amount:50,
    });
    assert.equal(totals.subtotal, '200.00');
    assert.equal(totals.discount, '48.00');
    assert.equal(totals.total, '152.00');
    assert.equal(totals.remaining_amount, '102.00');
});
