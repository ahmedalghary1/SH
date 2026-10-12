import json
from datetime import timedelta
from decimal import Decimal
import json
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from customers.models import Customer
from customers.services import get_customer_summary
from finance.models import CashAccount, PaymentTransaction
from finance.services import collect_customer_balance_payment, collect_order_payment, record_transaction
from inventory.models import Stock, StockBatch, StockMovement, Warehouse
from inventory.services import sale_stock, stock_in, transfer_stock
from invoices.models import Invoice
from invoices.services import delete_invoice, generate_invoice
from orders.models import Order
from orders.services import create_order, revise_order
from products.models import Product, ProductVariant
from purchases.models import PurchaseOrder, Supplier
from purchases.services import create_purchase_order, receive_purchase_order_items
from returns.models import SalesReturn
from returns.services import add_exchange_item, add_return_item, approve_sales_return, complete_sales_return, create_sales_return
from sales_reps.models import SalesRepCollection


class BackendResilienceTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username='resilience-manager', role=User.ROLE_MANAGER)
        self.customer = Customer.objects.create(name='Resilience Customer')
        self.product = Product.objects.create(name='Resilience Product', sku='RES-001')
        self.variant = ProductVariant.objects.create(
            product=self.product, variant_sku='RES-001-V', cost_price=Decimal('10'),
            sale_price=Decimal('30'), retail_price=Decimal('30'), wholesale_price=Decimal('30'),
        )
        self.warehouse = Warehouse.objects.create(name='Resilience Warehouse')
        self.cash = CashAccount.objects.create(name='Resilience Cash')
        self.supplier = Supplier.objects.create(name='Resilience Supplier')
        stock_in(variant=self.variant, warehouse=self.warehouse, quantity=10, user=self.manager, unit_cost=Decimal('10'))
        self.client.force_login(self.manager)

    def order(self, *, customer=True, quantity=3, cash=True):
        order = create_order(
            order_data={'customer': self.customer if customer else None, 'warehouse': self.warehouse,
                        'order_type': Order.TYPE_B2C, 'payment_method': Order.METHOD_CREDIT,
                        'document_type': Order.DOCUMENT_SALE},
            items=[{'variant': self.variant, 'warehouse': self.warehouse, 'quantity': quantity,
                    'unit_price': Decimal('30')}], user=self.manager, confirm=True,
        )
        if cash:
            collect_order_payment(order=order, amount=order.total, user=self.manager, cash_account=self.cash)
            order.refresh_from_db()
        return order

    def purchase(self, **kwargs):
        return create_purchase_order(supplier=self.supplier, user=self.manager,
            items=[{'product_variant': self.variant, 'quantity': 2, 'unit_cost': Decimal('10')}], **kwargs)

    def test_invoice_creation_failure_rolls_back_order_stock_and_payment_without_submission_token(self):
        data = {'document_type': Order.DOCUMENT_SALE, 'order_type': Order.TYPE_B2C,
                'warehouse': str(self.warehouse.pk), 'customer': str(self.customer.pk),
                'payment_method': Order.METHOD_CASH, 'discount_amount': '0',
                'discount_percentage': '0', 'action': 'confirm',
                'items_json': json.dumps([{'variant_id': self.variant.pk, 'warehouse_id': self.warehouse.pk,
                                          'quantity': 1, 'unit_price': '30'}])}
        with patch('orders.views.generate_invoice', side_effect=ValidationError('Invoice generation failed')):
            response = self.client.post(reverse('orders:create'), data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.assertFalse(Order.objects.exists())
        self.assertFalse(PaymentTransaction.objects.exists())
        self.assertEqual(Stock.objects.get(variant=self.variant, warehouse=self.warehouse).quantity, 10)

    def test_posted_cash_customerless_invoice_can_be_revised_on_postgresql(self):
        order = self.order(customer=False)
        result = revise_order(order=order, user=self.manager,
            order_data={'customer': None, 'warehouse': self.warehouse, 'order_type': Order.TYPE_B2C,
                        'payment_method': Order.METHOD_CREDIT, 'document_type': Order.DOCUMENT_SALE},
            items=[{'variant': self.variant, 'warehouse': self.warehouse, 'quantity': 2, 'unit_price': Decimal('30')}])
        self.assertEqual(result.total, Decimal('60'))
        self.assertEqual(Stock.objects.get(variant=self.variant, warehouse=self.warehouse).quantity, 8)

    def test_bulk_price_update_with_nullable_color_size_category_on_postgresql(self):
        response = self.client.post(reverse('products:bulk_price_update'), {
            'variant_id': str(self.variant.pk), f'price_{self.variant.pk}': '35.50',
        })
        self.assertEqual(response.status_code, 302)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.sale_price, Decimal('35.50'))

    def test_nonfinite_or_oversized_cash_amount_is_rejected_without_side_effects(self):
        for amount in ['NaN', 'sNaN', 'Infinity', '-Infinity', 'abc', '1e100', '0.001']:
            with self.subTest(amount=amount), self.assertRaises(ValidationError):
                record_transaction(transaction_type=PaymentTransaction.TYPE_CUSTOMER_PAYMENT,
                    direction=PaymentTransaction.DIRECTION_IN, amount=amount, cash_account=self.cash,
                    created_by=self.manager)
        self.cash.refresh_from_db()
        self.assertEqual(self.cash.balance, 0)
        self.assertFalse(PaymentTransaction.objects.exists())

    def test_invalid_stock_quantities_cannot_create_stock_or_movements(self):
        before = StockMovement.objects.count()
        for quantity in [0, -1, '1.5', 'NaN', 'Infinity', 2147483648]:
            with self.subTest(quantity=quantity), self.assertRaises(ValidationError):
                sale_stock(variant=self.variant, warehouse=self.warehouse, quantity=quantity, user=self.manager)
        self.assertEqual(Stock.objects.get(variant=self.variant, warehouse=self.warehouse).quantity, 10)
        self.assertEqual(StockMovement.objects.count(), before)

    def test_stock_transfer_preserves_costed_batches(self):
        target = Warehouse.objects.create(name='Resilience Target')
        transfer_stock(variant=self.variant, from_warehouse=self.warehouse, to_warehouse=target,
                       quantity=2, user=self.manager)
        self.assertEqual(Stock.objects.get(warehouse=target, variant=self.variant).quantity, 2)
        self.assertEqual(StockBatch.objects.get(warehouse=target, variant=self.variant).unit_cost, Decimal('10'))
        self.assertEqual(StockBatch.objects.get(warehouse=self.warehouse, variant=self.variant).remaining_quantity, 8)

    def test_purchase_sequence_survives_deleting_an_older_invoice(self):
        first = self.purchase()
        second = self.purchase()
        first.delete()
        third = self.purchase()
        self.assertNotEqual(second.purchase_number, third.purchase_number)
        self.assertTrue(third.purchase_number.endswith('-0003'))

    def test_backdated_purchase_sequence_is_allocated_for_its_date(self):
        backdate = timezone.now() - timedelta(days=15)
        first = self.purchase(invoice_datetime=backdate)
        second = self.purchase(invoice_datetime=backdate)
        self.assertTrue(first.purchase_number.startswith(f'PO-{timezone.localtime(backdate):%Y%m%d}-'))
        self.assertTrue(second.purchase_number.endswith('-0002'))

    def test_invalid_purchase_item_id_is_form_error_instead_of_500(self):
        response = self.client.post(reverse('purchases:order_create'), {
            'supplier': self.supplier.pk, 'warehouse': self.warehouse.pk,
            'items_json': json.dumps([{'variant_id': 'bad-id', 'quantity': 1, 'unit_cost': '10'}]),
            'discount_type': PurchaseOrder.DISCOUNT_FIXED, 'discount_value': '0',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(PurchaseOrder.objects.exists())

    def test_receive_unknown_item_rolls_back_without_server_error(self):
        purchase = self.purchase()
        before = StockMovement.objects.count()
        with self.assertRaises(ValidationError):
            receive_purchase_order_items(purchase_order=purchase, warehouse=self.warehouse,
                                         received_items={'bad-id': 1}, user=self.manager)
        self.assertEqual(StockMovement.objects.count(), before)

    def test_repeated_return_lines_cannot_exceed_original_quantity(self):
        order = self.order()
        sales_return = create_sales_return(order=order, return_type=SalesReturn.TYPE_REFUND, user=self.manager)
        item = order.items.get()
        add_return_item(sales_return=sales_return, original_order_item=item, quantity=2)
        with self.assertRaises(ValidationError):
            add_return_item(sales_return=sales_return, original_order_item=item, quantity=2)
        self.assertEqual(sales_return.items.count(), 1)

    def test_overlapping_returns_are_rechecked_at_completion(self):
        order = self.order()
        returns = []
        for _ in range(2):
            sales_return = create_sales_return(order=order, return_type=SalesReturn.TYPE_REFUND, user=self.manager)
            add_return_item(sales_return=sales_return, original_order_item=order.items.get(), quantity=2)
            approve_sales_return(sales_return=sales_return, user=self.manager)
            returns.append(sales_return)
        complete_sales_return(sales_return=returns[0], user=self.manager, cash_account=self.cash)
        before = self.cash.transactions.count()
        with self.assertRaises(ValidationError):
            complete_sales_return(sales_return=returns[1], user=self.manager, cash_account=self.cash)
        self.assertEqual(self.cash.transactions.count(), before)
        self.assertEqual(Stock.objects.get(variant=self.variant, warehouse=self.warehouse).quantity, 9)

    def test_return_and_exchange_keep_batch_quantities_and_original_cost(self):
        order = self.order()
        sales_return = create_sales_return(order=order, return_type=SalesReturn.TYPE_EXCHANGE, user=self.manager)
        add_return_item(sales_return=sales_return, original_order_item=order.items.get(), quantity=1)
        add_exchange_item(sales_return=sales_return, old_order_item=order.items.get(), new_product_variant=self.variant,
                          quantity=1, new_unit_price=Decimal('30'))
        approve_sales_return(sales_return=sales_return, user=self.manager)
        complete_sales_return(sales_return=sales_return, user=self.manager, cash_account=self.cash)
        batches = StockBatch.objects.filter(variant=self.variant, warehouse=self.warehouse)
        self.assertEqual(sum(batch.remaining_quantity for batch in batches), 7)
        self.assertTrue(batches.filter(source='return', unit_cost=Decimal('10')).exists())

    def test_invalid_days_dates_and_ids_do_not_crash_reports(self):
        cases = [
            ('reports:inactive_customers', {'days': 'NaN'}),
            ('reports:stale_products', {'days': '99999999999999999999'}),
            ('reports:stock_movement', {'date_from': '2026-02-30', 'date_to': 'not-a-date', 'warehouse': 'bad'}),
            ('reports:sales', {'customer': 'bad', 'employee': '9' * 80}),
            ('products:list', {'category': 'bad'}),
            ('products:api_products', {'warehouse': '9' * 80, 'color': 'bad'}),
        ]
        for url_name, params in cases:
            with self.subTest(url=url_name):
                self.assertEqual(self.client.get(reverse(url_name), params).status_code, 200)

    def test_bad_stock_ajax_id_returns_actionable_client_error(self):
        response = self.client.get(reverse('inventory:ajax_check_stock'), {'variant_id': 'bad', 'warehouse_id': '9' * 80})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['success'])

    def test_invoice_deletion_restores_stock_cash_debt_and_is_idempotent(self):
        order = self.order(cash=False)
        collect_order_payment(order=order, amount=Decimal('30'), user=self.manager, cash_account=self.cash)
        invoice = generate_invoice(order, user=self.manager)
        delete_invoice(invoice=invoice, user=self.manager)
        delete_invoice(invoice=invoice, user=self.manager)
        order.refresh_from_db()
        self.cash.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_CANCELLED)
        self.assertEqual(order.remaining_amount, 0)
        self.assertEqual(self.cash.balance, 0)
        self.assertEqual(Stock.objects.get(variant=self.variant, warehouse=self.warehouse).quantity, 10)
        self.assertEqual(get_customer_summary(self.customer)['total_remaining'], 0)
        self.assertTrue(Invoice.objects.filter(pk=invoice.pk).exists())
        self.assertEqual(PaymentTransaction.objects.filter(transaction_type=PaymentTransaction.TYPE_REFUND).count(), 1)
        response = self.client.get(reverse('invoices:list'))
        self.assertNotContains(response, invoice.invoice_number)

    def test_invoice_deletion_refunds_original_accounts_and_never_other_customer_receipts(self):
        other_cash = CashAccount.objects.create(name='Other Cash')
        order = self.order(cash=False)
        collect_order_payment(order=order, amount=Decimal('30'), user=self.manager, cash_account=self.cash)
        collect_order_payment(order=order, amount=Decimal('20'), user=self.manager, cash_account=other_cash)
        record_transaction(transaction_type=PaymentTransaction.TYPE_CUSTOMER_PAYMENT,
            direction=PaymentTransaction.DIRECTION_IN, amount=Decimal('15'), cash_account=self.cash,
            related_customer=self.customer, created_by=self.manager)
        invoice = generate_invoice(order, user=self.manager)
        delete_invoice(invoice=invoice, user=self.manager)
        self.cash.refresh_from_db()
        other_cash.refresh_from_db()
        self.assertEqual(self.cash.balance, Decimal('15'))
        self.assertEqual(other_cash.balance, 0)

    def test_invoice_deletion_refunds_only_its_share_of_customer_receipt(self):
        first = self.order(quantity=2, cash=False)
        second = self.order(quantity=2, cash=False)
        collect_customer_balance_payment(customer=self.customer, amount=Decimal('100'), user=self.manager, cash_account=self.cash)
        invoice = generate_invoice(first, user=self.manager)
        delete_invoice(invoice=invoice, user=self.manager)
        self.cash.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(self.cash.balance, Decimal('40'))
        self.assertEqual(second.paid_amount, Decimal('40'))
        self.assertEqual(second.remaining_amount, Decimal('20'))

    def test_invoice_deletion_does_not_refund_unrecorded_paid_amount(self):
        order = self.order(cash=False)
        Order.objects.filter(pk=order.pk).update(paid_amount=Decimal('90'), remaining_amount=0)
        invoice = generate_invoice(order, user=self.manager)
        delete_invoice(invoice=invoice, user=self.manager)
        self.assertFalse(PaymentTransaction.objects.filter(transaction_type=PaymentTransaction.TYPE_REFUND).exists())

    def test_invoice_deletion_failure_rolls_back_stock_and_keeps_invoice(self):
        order = self.order()
        invoice = generate_invoice(order, user=self.manager)
        self.cash.balance = 0
        self.cash.save(update_fields=['balance'])
        before_batches = StockBatch.objects.count()
        with self.assertRaises(ValidationError):
            delete_invoice(invoice=invoice, user=self.manager)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_CONFIRMED)
        self.assertEqual(Stock.objects.get(variant=self.variant, warehouse=self.warehouse).quantity, 7)
        self.assertEqual(StockBatch.objects.count(), before_batches)

    def test_invoice_deletion_rejects_existing_return_without_reversing_twice(self):
        order = self.order()
        invoice = generate_invoice(order, user=self.manager)
        create_sales_return(order=order, return_type=SalesReturn.TYPE_REFUND, user=self.manager)
        with self.assertRaises(ValidationError):
            delete_invoice(invoice=invoice, user=self.manager)
        self.assertEqual(Stock.objects.get(variant=self.variant, warehouse=self.warehouse).quantity, 7)

    def test_invoice_delete_endpoint_requires_manager_and_post_for_mutation(self):
        order = self.order()
        invoice = generate_invoice(order, user=self.manager)
        response = self.client.get(reverse('invoices:delete', args=[invoice.pk]))
        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_CONFIRMED)
        sales = User.objects.create_user(username='resilience-sales', role=User.ROLE_SALES)
        with self.assertRaises(PermissionDenied):
            delete_invoice(invoice=invoice, user=sales)
        self.client.force_login(sales)
        self.assertEqual(self.client.post(reverse('invoices:delete', args=[invoice.pk])).status_code, 403)

    def test_cancelled_invoice_cannot_collect_new_money(self):
        order = self.order()
        invoice = generate_invoice(order, user=self.manager)
        delete_invoice(invoice=invoice, user=self.manager)
        with self.assertRaises(ValidationError):
            collect_order_payment(order=order, amount=Decimal('10'), user=self.manager, cash_account=self.cash)
