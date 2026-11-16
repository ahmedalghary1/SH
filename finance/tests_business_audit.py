"""Accounting invariants across complete business workflows, on disposable data."""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import RequestFactory, TestCase
from django.utils import timezone

from accounts.models import User
from customers.models import Customer
from customers.services import annotate_customer_balances, get_customer_summary
from finance.models import CashAccount, PaymentTransaction
from finance.services import (build_customer_statement, collect_order_payment,
                              delete_transaction, record_transaction)
from inventory.models import Stock, StockBatch
from inventory.services import stock_in
from orders.models import Order
from orders.services import calculate_order_totals, cancel_order, create_order
from products.models import Product, ProductVariant
from purchases.models import Supplier
from purchases.services import (create_purchase_order, create_purchase_return,
                                pay_supplier, update_purchase_discount)
from returns.models import SalesReturn
from returns.services import (add_return_item, approve_sales_return,
                              complete_sales_return, create_sales_return)
from sales_reps.services import record_sales_rep_collection


class BusinessAccountingAuditTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username='business-manager', role='manager')
        self.rep = User.objects.create_user(username='business-rep', role='sales')
        self.customer = Customer.objects.create(name='Business customer', created_by=self.manager)
        from inventory.models import Warehouse
        self.warehouse = Warehouse.objects.create(name='Business warehouse')
        product = Product.objects.create(name='Business product', sku='BUSINESS')
        self.variant = ProductVariant.objects.create(product=product, variant_sku='BUSINESS-V',
                                                     cost_price=10, retail_price=100)
        stock_in(variant=self.variant, warehouse=self.warehouse, quantity=100, unit_cost=10, user=self.manager)
        self.cash = CashAccount.objects.create(name='Business cash', balance=10000)

    def sale(self, *, quantity=3, price='100', fixed='0', percent='0', item_percent='0', confirmed=True):
        return create_order(order_data={'customer': self.customer, 'warehouse': self.warehouse,
            'order_type': 'b2c', 'payment_method': 'credit', 'discount_amount': Decimal(fixed),
            'discount_percentage': Decimal(percent)},
            items=[{'variant': self.variant, 'quantity': quantity, 'unit_price': Decimal(price),
                    'discount_percentage': Decimal(item_percent)}], user=self.manager, confirm=confirmed)

    def returned(self, order, quantity=1):
        result = create_sales_return(order=order, return_type=SalesReturn.TYPE_PARTIAL_RETURN, user=self.manager)
        add_return_item(sales_return=result, original_order_item=order.items.get(), quantity=quantity)
        approve_sales_return(sales_return=result, user=self.manager)
        return complete_sales_return(sales_return=result, user=self.manager, cash_account=self.cash)

    def assert_customer_balance(self, expected):
        self.customer.refresh_from_db()
        expected = Decimal(expected)
        self.assertEqual(build_customer_statement(self.customer)['current_balance'], expected)
        self.assertEqual(get_customer_summary(self.customer)['total_remaining'], expected)
        self.assertEqual(annotate_customer_balances(Customer.objects.filter(pk=self.customer.pk)).get().current_balance, expected)

    def assert_cash_matches_ledger(self):
        self.cash.refresh_from_db()
        delta = sum((row.amount if row.direction == 'in' else -row.amount
                     for row in self.cash.transactions.filter(affects_cash=True)), Decimal(0))
        self.assertEqual(self.cash.balance, Decimal(10000) + delta)

    def test_invoice_percentage_recalculation_is_idempotent(self):
        order = self.sale(percent='10', confirmed=False)
        self.assertEqual(order.total, Decimal('270'))
        for _ in range(3):
            with transaction.atomic():
                calculate_order_totals(order)
            order.refresh_from_db()
            self.assertEqual(order.total, Decimal('270'))

    def test_line_percentage_recalculation_is_idempotent(self):
        order = self.sale(item_percent='5', confirmed=False)
        for _ in range(3):
            with transaction.atomic():
                calculate_order_totals(order)
            order.refresh_from_db()
            self.assertEqual(order.total, Decimal('285'))

    def test_partial_return_includes_the_invoice_discount(self):
        order = self.sale(percent='10')
        result = self.returned(order)
        self.assertEqual(result.refund_amount, Decimal('90'))
        self.assert_customer_balance('180')

    def test_full_return_never_refunds_more_than_the_discounted_invoice(self):
        order = self.sale(fixed='50')
        collect_order_payment(order=order, amount=250, user=self.manager, cash_account=self.cash)
        result = self.returned(order, quantity=3)
        self.assertEqual(result.refund_amount, Decimal('250'))
        self.assert_cash_matches_ledger()
        self.assertEqual(CashAccount.objects.get(pk=self.cash.pk).balance, Decimal(10000))
        self.assert_customer_balance('0')

    def test_separate_rounded_returns_sum_to_the_original_total(self):
        order = self.sale(price='100', fixed='0.01')
        results = [self.returned(order) for _ in range(3)]
        self.assertEqual(sum((result.refund_amount for result in results), Decimal(0)), Decimal('299.99'))
        self.assert_customer_balance('0')

    def test_rep_collection_preserves_return_credit(self):
        order = self.sale()
        self.returned(order)
        record_sales_rep_collection(sales_rep=self.rep, customer=self.customer, order=order,
                                    amount=50, cash_account=self.cash, user=self.manager)
        order.refresh_from_db()
        self.assertEqual(order.remaining_amount, Decimal('150'))
        self.assert_customer_balance('150')
        self.assert_cash_matches_ledger()

    def test_rep_refund_preserves_return_credit(self):
        order = self.sale()
        collect_order_payment(order=order, amount=50, user=self.manager, cash_account=self.cash)
        self.returned(order)
        record_sales_rep_collection(sales_rep=self.rep, customer=self.customer, order=order,
                                    amount=-20, cash_account=self.cash, user=self.manager)
        self.assert_customer_balance('170')

    def test_rep_collection_rejects_a_mismatched_customer(self):
        order = self.sale()
        other = Customer.objects.create(name='Different customer')
        with self.assertRaises(ValidationError):
            record_sales_rep_collection(sales_rep=self.rep, customer=other, order=order,
                                        amount=20, cash_account=self.cash, user=self.manager)

    def test_rep_collection_rejects_cancelled_invoices(self):
        order = self.sale()
        cancel_order(order=order, user=self.manager)
        with self.assertRaises(ValidationError):
            record_sales_rep_collection(sales_rep=self.rep, customer=self.customer, order=order,
                                        amount=20, cash_account=self.cash, user=self.manager)

    def test_original_receipt_cannot_be_deleted_after_invoice_cancellation(self):
        order = self.sale()
        payment = collect_order_payment(order=order, amount=100, user=self.manager, cash_account=self.cash)
        cancel_order(order=order, user=self.manager)
        with self.assertRaises(ValidationError):
            delete_transaction(payment_transaction=payment, user=self.manager)
        self.assert_cash_matches_ledger()

    def test_transfer_leg_cannot_be_deleted_in_isolation(self):
        from finance.services import transfer_between_accounts
        target = CashAccount.objects.create(name='Business target')
        outgoing, _ = transfer_between_accounts(from_account=self.cash, to_account=target,
                                                 amount=100, user=self.manager)
        with self.assertRaises(ValidationError):
            delete_transaction(payment_transaction=outgoing, user=self.manager)

    def test_purchase_discount_cannot_discard_an_existing_overpayment(self):
        supplier = Supplier.objects.create(name='Business supplier')
        order = create_purchase_order(supplier=supplier,
            items=[{'product_variant': self.variant, 'quantity': 10, 'unit_cost': 10}], user=self.manager)
        pay_supplier(purchase_order=order, amount=80, cash_account=self.cash, user=self.manager)
        with self.assertRaises(ValidationError):
            update_purchase_discount(purchase_order=order, discount_type='fixed', discount_value=50, user=self.manager)
        order.refresh_from_db()
        self.assertEqual(order.total_amount, Decimal(100))
        self.assertEqual(order.remaining_amount, Decimal(20))

    def test_purchase_return_appears_in_supplier_statement(self):
        from purchases.views import SimpleSupplierDetailView
        supplier = Supplier.objects.create(name='Return supplier')
        create_purchase_order(supplier=supplier,
            items=[{'product_variant': self.variant, 'quantity': 10, 'unit_cost': 10}], user=self.manager)
        create_purchase_return(supplier=supplier, product_variant=self.variant, warehouse=self.warehouse,
                                quantity=2, unit_cost=10, user=self.manager)
        supplier.refresh_from_db()
        view = SimpleSupplierDetailView()
        statement = view._generate_statement(supplier, supplier.purchase_orders.all(),
                                             PaymentTransaction.objects.filter(related_supplier=supplier))
        self.assertEqual(statement[-1]['balance'], supplier.current_balance)

    def test_supplier_statement_does_not_count_unposted_drafts(self):
        from purchases.views import SimpleSupplierDetailView
        supplier = Supplier.objects.create(name='Draft supplier')
        create_purchase_order(supplier=supplier, status='draft',
            items=[{'product_variant': self.variant, 'quantity': 10, 'unit_cost': 10}], user=self.manager)
        statement = SimpleSupplierDetailView()._generate_statement(supplier, supplier.purchase_orders.all(),
                                                                  PaymentTransaction.objects.none())
        self.assertEqual(sum((row['debit'] or 0 for row in statement), Decimal(0)), Decimal(0))

    def test_expense_report_uses_effective_transaction_date(self):
        from datetime import timedelta
        from reports.services import net_profit_report
        yesterday = timezone.localdate() - timedelta(days=1)
        record_transaction(transaction_type='expense', direction='out', amount=25,
                           cash_account=self.cash, created_by=self.manager, transaction_date=yesterday)
        request = RequestFactory().get('/', {'date_from': str(yesterday), 'date_to': str(yesterday)})
        request.user = self.manager
        self.assertEqual(net_profit_report(request)['summary']['expenses'], Decimal(25))

    def test_dashboard_collection_counts_real_receipt_once_and_excludes_transfers(self):
        from finance.services import collect_customer_balance_payment, transfer_between_accounts
        from reports.services import manager_dashboard_kpis
        self.sale()
        collect_customer_balance_payment(customer=self.customer, amount=100,
                                         cash_account=self.cash, user=self.manager)
        target = CashAccount.objects.create(name='Dashboard transfer')
        transfer_between_accounts(from_account=self.cash, to_account=target, amount=50, user=self.manager)
        self.assertEqual(manager_dashboard_kpis()['today_collections'], Decimal(100))

    def test_cash_dashboard_historical_opening_excludes_later_movements(self):
        from datetime import timedelta
        from django.urls import reverse
        yesterday = timezone.localdate() - timedelta(days=1)
        record_transaction(transaction_type='customer_payment', direction='in', amount=100,
                           cash_account=self.cash, created_by=self.manager, transaction_date=yesterday)
        record_transaction(transaction_type='customer_payment', direction='in', amount=50,
                           cash_account=self.cash, created_by=self.manager)
        self.client.force_login(self.manager)
        response = self.client.get(reverse('finance:cash'), {'account': self.cash.pk,
            'date_from': str(yesterday), 'date_to': str(yesterday)})
        self.assertEqual(response.context['opening_balance'], Decimal(10000))

    def test_allowed_discount_updates_debt_and_does_not_block_later_returns(self):
        from finance.services import record_customer_allowed_discount
        order = self.sale()
        record_customer_allowed_discount(customer=self.customer, order=order, amount=10,
                                         user=self.manager, cash_account=self.cash)
        order.refresh_from_db()
        self.assertEqual(order.remaining_amount, Decimal(290))
        self.returned(order)
        self.assert_customer_balance('190')

    def test_return_edit_keeps_the_rounding_cent_when_quantity_changes(self):
        from returns.services import update_sales_return
        order = self.sale(fixed='0.01')
        result = self.returned(order)
        row = result.items.get()
        result = update_sales_return(sales_return=result, user=self.manager, revision=result.revision,
            items=[{'item_id': row.pk, 'original_order_item': order.items.get(),
                    'quantity': 3, 'condition': 'good', 'return_to_stock': True}],
            return_warehouse=self.warehouse)
        self.assertEqual(result.refund_amount, Decimal('299.99'))

    def test_recalculating_fifo_cost_keeps_exact_line_cost(self):
        # Three pieces cost 10 + 10 + 11; storing an average 10.33 cannot reconstruct 31.
        Stock.objects.filter(variant=self.variant, warehouse=self.warehouse).update(quantity=0)
        StockBatch.objects.filter(variant=self.variant, warehouse=self.warehouse).delete()
        stock_in(variant=self.variant, warehouse=self.warehouse, quantity=2, unit_cost=10, user=self.manager)
        stock_in(variant=self.variant, warehouse=self.warehouse, quantity=1, unit_cost=11, user=self.manager)
        order = self.sale()
        self.assertEqual(order.total_cost, Decimal(31))
        with transaction.atomic():
            calculate_order_totals(order)
        order.refresh_from_db()
        self.assertEqual(order.total_cost, Decimal(31))

    def test_full_exchange_keeps_original_credit_invoice_collectable(self):
        from returns.services import add_exchange_item
        product = Product.objects.create(name='Exchange product', sku='BUSINESS-EX')
        variant = ProductVariant.objects.create(product=product, variant_sku='BUSINESS-EX-V', cost_price=20)
        stock_in(variant=variant, warehouse=self.warehouse, quantity=3, unit_cost=20, user=self.manager)
        order = self.sale()
        result = create_sales_return(order=order, return_type=SalesReturn.TYPE_EXCHANGE, user=self.manager)
        add_return_item(sales_return=result, original_order_item=order.items.get(), quantity=3)
        add_exchange_item(sales_return=result, old_order_item=order.items.get(), new_product_variant=variant,
                          quantity=3, new_unit_price=110)
        approve_sales_return(sales_return=result, user=self.manager)
        complete_sales_return(sales_return=result, user=self.manager, cash_account=self.cash)
        self.assert_customer_balance('300')
        collect_order_payment(order=order, amount=300, user=self.manager, cash_account=self.cash)
        self.assert_customer_balance('0')

    def test_deleting_history_owners_is_rejected_without_losing_stock_or_debt(self):
        from django.db.models.deletion import ProtectedError
        order = self.sale()
        for record in (self.customer, self.variant.product, self.variant, self.warehouse,
                       Stock.objects.get(variant=self.variant, warehouse=self.warehouse)):
            with self.subTest(model=record._meta.label):
                with self.assertRaises(ProtectedError), transaction.atomic():
                    record.delete()
        self.assert_customer_balance('300')
        self.assertEqual(Stock.objects.get(variant=self.variant, warehouse=self.warehouse).quantity, 97)

    def test_full_return_does_not_refund_a_non_cash_allowed_discount(self):
        from finance.services import record_customer_allowed_discount
        order = self.sale()
        record_customer_allowed_discount(customer=self.customer, order=order, amount=10,
                                         user=self.manager, cash_account=self.cash)
        result = self.returned(order, quantity=3)
        self.assertEqual(result.refund_amount, Decimal(290))
        self.assertEqual(CashAccount.objects.get(pk=self.cash.pk).balance, Decimal(10000))
        self.assert_customer_balance('0')

    def test_raw_material_cash_purchase_does_not_create_a_supplier_credit(self):
        from purchases.raw_material import record_raw_material_purchase
        from purchases.views import SimpleSupplierDetailView
        supplier = Supplier.objects.create(name='Raw supplier')
        default = CashAccount.get_default()
        default.balance = 1000
        default.save(update_fields=['balance'])
        record_raw_material_purchase(raw_name='Cotton', supplier=supplier, amount=100, user=self.manager)
        supplier.refresh_from_db()
        statement = SimpleSupplierDetailView()._generate_statement(supplier, supplier.purchase_orders.all(),
            PaymentTransaction.objects.filter(related_supplier=supplier))
        self.assertEqual(statement[-1]['balance'], supplier.current_balance)
        self.assertEqual(supplier.current_balance, Decimal(0))

    def test_audit_command_is_read_only_and_detects_inconsistent_invoice(self):
        import json
        from io import StringIO
        from django.core.management import call_command
        from audit.models import AuditLog
        order = self.sale()
        Order.objects.filter(pk=order.pk).update(total=299)
        before = AuditLog.objects.count()
        output = StringIO()
        call_command('audit_business', stdout=output)
        report = json.loads(output.getvalue())
        self.assertGreaterEqual(report['finding_count'], 3)
        order.refresh_from_db()
        self.assertEqual(order.total, Decimal(299))
        self.assertEqual(AuditLog.objects.count(), before)
        Customer.objects.create(name='Read-only mode was restored')

    def test_profit_report_deducts_completed_returns_and_recovered_cost(self):
        from reports.services import profitability_report
        order = self.sale(percent='10')
        self.returned(order)
        request = RequestFactory().get('/')
        request.user = self.manager
        report = profitability_report(request)
        self.assertEqual(report['summary']['total_sales'], Decimal(180))
        self.assertEqual(report['summary']['total_cost'], Decimal(20))
        self.assertEqual(report['summary']['gross_profit'], Decimal(160))
        for rows in report['sections'].values():
            self.assertEqual(sum((row['profit'] for row in rows), Decimal(0)), Decimal(160))

    def test_profit_report_full_return_is_zero_for_good_stock(self):
        from reports.services import profitability_report
        order = self.sale()
        self.returned(order, quantity=3)
        request = RequestFactory().get('/')
        request.user = self.manager
        summary = profitability_report(request)['summary']
        self.assertEqual(summary['total_sales'], Decimal(0))
        self.assertEqual(summary['total_cost'], Decimal(0))
        self.assertEqual(summary['gross_profit'], Decimal(0))

    def test_fractional_line_discounts_sum_to_the_stored_header(self):
        self.variant.cost_price = 0
        self.variant.save(update_fields=['cost_price'])
        order = create_order(order_data={'customer': self.customer, 'warehouse': self.warehouse,
            'order_type': 'b2c', 'payment_method': 'credit'},
            items=[{'variant': self.variant, 'quantity': 1, 'unit_price': '1.01',
                    'discount_percentage': '50'} for _ in range(2)], user=self.manager, confirm=False)
        order.refresh_from_db()
        self.assertEqual(order.total, Decimal('1.00'))
        self.assertEqual(sum((line.total for line in order.items.all()), Decimal(0)), order.total)

    def test_general_discount_cannot_bypass_actual_fifo_cost_policy(self):
        self.variant.cost_price = 95
        self.variant.save(update_fields=['cost_price'])
        StockBatch.objects.filter(variant=self.variant).update(unit_cost=95)
        before = Stock.objects.get(variant=self.variant, warehouse=self.warehouse).quantity
        with self.assertRaises(ValidationError):
            self.sale(percent='10')
        self.assertEqual(Stock.objects.get(variant=self.variant, warehouse=self.warehouse).quantity, before)
        self.assertFalse(Order.objects.exists())

    def test_customer_debt_report_includes_opening_balance_and_ledger_credits(self):
        from reports.services import customer_debt_report
        self.customer.opening_balance = 50
        self.customer.save(update_fields=['opening_balance'])
        order = self.sale()
        collect_order_payment(order=order, amount=100, user=self.manager, cash_account=self.cash)
        self.assertEqual(customer_debt_report()['summary']['total_debt'], Decimal(250))

    def test_legacy_finance_rep_entry_point_uses_the_same_payment_balance_rules(self):
        from finance.services import record_sales_rep_collection as finance_collection
        order = self.sale()
        self.returned(order)
        finance_collection(sales_rep=self.rep, customer=self.customer, order=order,
            amount=50, user=self.manager, cash_account=self.cash)
        self.assert_customer_balance('150')
        self.assert_cash_matches_ledger()
