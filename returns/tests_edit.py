from datetime import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import Branch, User
from finance.models import PaymentTransaction
from finance.services import (
    build_customer_statement,
    collect_order_payment,
    delete_transaction,
)
from inventory.models import Stock, StockBatch, StockMovement, Warehouse
from orders.models import OrderItem
from products.models import Color, Size

from . import tests as legacy_tests
from .models import SalesReturn
from .services import (
    add_exchange_item,
    add_return_item,
    approve_sales_return,
    complete_sales_return,
    create_sales_return,
    update_sales_return,
)


class SalesReturnEditTests(TestCase):
    def setUp(self):
        legacy_tests.SalesReturnServiceTests.setUp(self)
        self.order.paid_amount = Decimal(0)
        self.order.remaining_amount = Decimal(900)
        self.order.save(update_fields=['paid_amount', 'remaining_amount'])
        self.target = Warehouse.objects.create(name='Returns warehouse', warehouse_type=Warehouse.TYPE_MAIN)

    def make_return(self, quantity=1, paid=0, completed=True, exchange=False, warehouse=None):
        if paid:
            collect_order_payment(order=self.order, amount=paid, cash_account=self.cash, user=self.user)
        sales_return = create_sales_return(
            order=self.order, user=self.user,
            return_type=SalesReturn.TYPE_EXCHANGE if exchange else SalesReturn.TYPE_PARTIAL_RETURN,
            return_warehouse=warehouse,
        )
        add_return_item(sales_return=sales_return, original_order_item=self.order_item, quantity=quantity)
        if exchange:
            add_exchange_item(sales_return=sales_return, old_order_item=self.order_item,
                              new_product_variant=self.exchange_variant, quantity=quantity, new_unit_price=380)
        if completed:
            approve_sales_return(sales_return=sales_return, user=self.user)
            complete_sales_return(sales_return=sales_return, user=self.user, cash_account=self.cash)
        sales_return.refresh_from_db()
        return sales_return

    def edit(self, sales_return, quantity=1, **kwargs):
        item = sales_return.items.get()
        row = {'item_id': item.pk, 'original_order_item': item.original_order_item,
                   'quantity': quantity, 'condition': item.condition, 'return_to_stock': item.return_to_stock}
        row.update(kwargs.pop('item_changes', {}))
        return update_sales_return(
            sales_return=sales_return, user=self.user, revision=sales_return.revision,
            items=[row], return_warehouse=kwargs.pop('return_warehouse', sales_return.return_warehouse),
            cash_account=self.cash, **kwargs,
        )

    def balance(self, amount):
        statement = build_customer_statement(self.customer)
        self.assertEqual(statement['current_balance'], Decimal(amount))
        self.assertEqual(statement['statement_opening_balance'], Decimal(0))

    def test_draft_edits_quantity_date_and_warehouse_without_posting(self):
        sales_return = self.make_return(completed=False)
        selected = datetime(2026, 10, 5, 14, 30, tzinfo=timezone.get_current_timezone())
        updated = self.edit(sales_return, quantity=2, reason='Updated reason',
                            return_warehouse=self.target, return_datetime=selected)
        self.assertEqual(updated.refund_amount, Decimal(600))
        self.assertEqual(updated.created_at, selected)
        self.assertEqual(updated.return_warehouse, self.target)
        self.assertEqual(updated.reason, 'Updated reason')
        self.assertFalse(PaymentTransaction.objects.exists())
        self.assertFalse(StockMovement.objects.exists())
        self.assertEqual(Stock.objects.get(warehouse=self.warehouse, variant=self.variant).quantity, 0)

    def test_approved_edit_requires_new_approval(self):
        sales_return = self.make_return(completed=False)
        approve_sales_return(sales_return=sales_return, user=self.user)
        sales_return.refresh_from_db()
        updated = self.edit(sales_return, quantity=2)
        self.assertEqual(updated.status, SalesReturn.STATUS_DRAFT)
        self.assertIsNone(updated.approved_by)
        with self.assertRaises(ValidationError):
            complete_sales_return(sales_return=updated, user=self.user)

    def test_completed_credit_edit_adjusts_debt_and_stock_only_by_difference(self):
        sales_return = self.make_return()
        updated = self.edit(sales_return, quantity=2)
        self.balance('300')
        self.assertEqual(updated.debt_reduction, Decimal(600))
        self.assertEqual(Stock.objects.get(warehouse=self.warehouse, variant=self.variant).quantity, 2)
        updated = self.edit(updated, quantity=1)
        self.balance('600')
        self.assertEqual(updated.debt_reduction, Decimal(300))
        self.assertFalse(PaymentTransaction.objects.exists())

    def test_cash_return_decrease_collects_only_refund_difference(self):
        sales_return = self.make_return(quantity=2, paid=900)
        self.cash.refresh_from_db()
        before = self.cash.balance
        updated = self.edit(sales_return, quantity=1)
        self.cash.refresh_from_db()
        self.assertEqual(self.cash.balance, before + Decimal(300))
        self.balance('0')
        self.assertEqual(updated.financial_transactions.count(), 2)
        transactions = PaymentTransaction.objects.count()
        movements = StockMovement.objects.count()
        self.edit(updated, quantity=1)
        self.assertEqual(PaymentTransaction.objects.count(), transactions)
        self.assertEqual(StockMovement.objects.count(), movements)

    def test_mixed_return_reverses_cash_before_reopening_debt(self):
        sales_return = self.make_return(quantity=2, paid=600)
        updated = self.edit(sales_return, quantity=1)
        self.order.refresh_from_db()
        self.assertEqual(self.order.remaining_amount, Decimal(0))
        self.assertEqual(updated.debt_reduction, Decimal(300))
        self.cash.refresh_from_db()
        self.assertEqual(self.cash.balance, Decimal(2600))
        self.balance('0')

    def test_decrease_after_later_settlement_reopens_correct_debt(self):
        sales_return = self.make_return(quantity=2)
        collect_order_payment(order=self.order, amount=300, cash_account=self.cash, user=self.user)
        self.edit(sales_return, quantity=1)
        self.balance('300')

    def test_completed_edit_moves_existing_stock_to_selected_warehouse(self):
        sales_return = self.make_return(quantity=2)
        self.edit(sales_return, quantity=2, return_warehouse=self.target)
        self.assertEqual(Stock.objects.get(warehouse=self.warehouse, variant=self.variant).quantity, 0)
        self.assertEqual(Stock.objects.get(warehouse=self.target, variant=self.variant).quantity, 2)
        self.assertEqual(sum(StockBatch.objects.filter(warehouse=self.target).values_list('remaining_quantity', flat=True)), 2)
        self.balance('300')

    def test_stock_shortage_rolls_back_every_change(self):
        sales_return = self.make_return(quantity=2, paid=900)
        from inventory.services import sale_stock
        sale_stock(variant=self.variant, warehouse=self.warehouse, quantity=2, user=self.user)
        transactions = PaymentTransaction.objects.count()
        movements = StockMovement.objects.count()
        with self.assertRaises(ValidationError):
            self.edit(sales_return, quantity=1, return_warehouse=self.target)
        sales_return.refresh_from_db()
        self.assertEqual(sales_return.refund_amount, Decimal(600))
        self.assertIsNone(sales_return.return_warehouse)
        self.assertEqual(PaymentTransaction.objects.count(), transactions)
        self.assertEqual(StockMovement.objects.count(), movements)
        self.assertFalse(Stock.objects.filter(warehouse=self.target, quantity__gt=0).exists())

    def test_changing_condition_withdraws_good_stock_without_changing_balance(self):
        sales_return = self.make_return()
        self.edit(sales_return, item_changes={'condition': 'damaged'})
        self.assertEqual(Stock.objects.get(warehouse=self.warehouse, variant=self.variant).quantity, 0)
        self.balance('600')

    def test_rejects_cross_branch_inactive_and_excess_quantity(self):
        sales_return = self.make_return()
        branch = Branch.objects.create(code='OTHER-RETURN-EDIT', name='Other')
        other = Warehouse.objects.create(branch=branch, name='Other', warehouse_type='main')
        self.target.is_active = False
        self.target.save(update_fields=['is_active'])
        for changes in ({'return_warehouse': other}, {'return_warehouse': self.target}, {'quantity': 4}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.edit(sales_return, **changes)

    def test_stale_edit_is_rejected(self):
        sales_return = self.make_return()
        self.edit(sales_return, quantity=2)
        with self.assertRaisesMessage(ValidationError, 'أعد تحميل الصفحة'):
            self.edit(sales_return, quantity=1)

    def test_exchange_edit_adjusts_replacement_stock_and_cash_difference(self):
        sales_return = self.make_return(exchange=True, paid=900)
        exchange = sales_return.exchange_items.get()
        self.edit(sales_return, exchanges=[{
            'item_id': exchange.pk, 'old_order_item': self.order_item, 'new_product_variant': self.exchange_variant,
            'quantity': 1, 'new_unit_price': 400,
        }])
        self.cash.refresh_from_db()
        self.assertEqual(self.cash.balance, Decimal(3000))
        self.assertEqual(Stock.objects.get(warehouse=self.warehouse, variant=self.exchange_variant).quantity, 4)
        self.balance('0')

    def test_linked_financial_transaction_cannot_be_deleted_separately(self):
        sales_return = self.make_return(paid=900)
        with self.assertRaisesMessage(ValidationError, 'مرتبطة بمرتجع'):
            delete_transaction(payment_transaction=sales_return.financial_transactions.get(), user=self.user)

    def test_completion_uses_selected_warehouse(self):
        sales_return = self.make_return(completed=False)
        approve_sales_return(sales_return=sales_return, user=self.user)
        complete_sales_return(sales_return=sales_return, user=self.user, return_warehouse=self.target)
        self.assertEqual(Stock.objects.get(warehouse=self.target, variant=self.variant).quantity, 1)
        self.assertEqual(Stock.objects.get(warehouse=self.warehouse, variant=self.variant).quantity, 0)

    def test_edit_page_and_post_update_draft_and_preserve_invalid_input(self):
        sales_return = self.make_return(completed=False)
        self.client.force_login(self.user)
        url = reverse('returns:edit', args=[sales_return.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="return_warehouse"')
        item = sales_return.items.get()
        data = {
            'revision': sales_return.revision, 'reason': 'Edited via form',
            'return_datetime': '2026-10-10T14:35', 'return_warehouse': self.target.pk,
            'items-TOTAL_FORMS': 2, 'items-INITIAL_FORMS': 1,
            'items-0-item_id': item.pk, 'items-0-original_order_item': self.order_item.pk,
            'items-0-quantity': 2, 'items-0-condition': 'good', 'items-0-return_to_stock': 'on',
            'items-1-condition': 'good', 'items-1-return_to_stock': 'on',
        }
        response = self.client.post(url, data)
        self.assertRedirects(response, reverse('returns:detail', args=[sales_return.pk]))
        sales_return.refresh_from_db()
        self.assertEqual(sales_return.refund_amount, Decimal(600))
        data.update(revision=sales_return.revision)
        data['items-0-quantity'] = 5
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'أكبر من المتاح')
        self.assertEqual(response.context['item_formset'][0]['quantity'].value(), '5')

    @override_settings(DEBUG=False)
    def test_opening_edit_page_does_not_query_color_and_size_for_every_invoice_line(self):
        color = Color.objects.create(name='Return edit color')
        size = Size.objects.create(name='Return edit size')
        self.variant.color = color
        self.variant.size = size
        self.variant.save(update_fields=['color', 'size'])
        sales_return = self.make_return()
        for _ in range(20):
            OrderItem.objects.create(order=self.order, variant=self.variant, quantity=1,
                                     unit_price=300, total=300)
        self.client.force_login(self.user)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse('returns:edit', args=[sales_return.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, color.name)
        related_queries = [query for query in queries.captured_queries if
                           'FROM "products_color"' in query['sql'] or 'FROM "products_size"' in query['sql']]
        self.assertLessEqual(len(related_queries), 2)

    @override_settings(DEBUG=False)
    def test_completed_exchange_edit_page_opens_with_production_settings(self):
        sales_return = self.make_return(exchange=True, paid=900)
        self.client.force_login(self.user)
        response = self.client.get(reverse('returns:edit', args=[sales_return.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="exchanges-0-new_unit_price"')
        self.assertContains(response, 'name="items-0-original_order_item"')

    def test_insufficient_cash_rolls_back_completed_edit(self):
        sales_return = self.make_return(paid=900)
        self.cash.balance = Decimal(0)
        self.cash.save(update_fields=['balance'])
        with self.assertRaisesMessage(ValidationError, 'رصيد الخزنة غير كاف'):
            self.edit(sales_return, quantity=2)
        sales_return.refresh_from_db()
        self.assertEqual(sales_return.refund_amount, Decimal(300))
        self.assertEqual(Stock.objects.get(warehouse=self.warehouse, variant=self.variant).quantity, 1)

    def test_legacy_migration_recovers_mixed_refund_links_before_edit(self):
        from importlib import import_module
        from types import SimpleNamespace

        from django.apps import apps

        sales_return = self.make_return(quantity=2, paid=600)
        sales_return.financial_transactions.clear()
        sales_return.debt_reduction = Decimal(0)
        sales_return.save(update_fields=['debt_reduction'])
        migration = import_module('returns.migrations.0003_salesreturn_debt_reduction_and_more')
        migration.link_existing_returns(apps, SimpleNamespace(connection=SimpleNamespace(alias='default')))
        sales_return.refresh_from_db()
        self.assertEqual(sales_return.debt_reduction, Decimal(300))
        self.assertEqual(sales_return.financial_transactions.count(), 1)
        self.edit(sales_return, quantity=1)
        self.balance('0')

    def test_synced_return_preserves_selected_warehouse_and_date(self):
        from sync_api.services import process_return

        response = process_return({
            'local_uuid': 'return-warehouse-sync',
            'payload': {
                'return': {'order_server_id': self.order.pk, 'return_warehouse': self.target.pk,
                           'return_datetime': '2026-10-10T14:35'},
                'items': [{'original_order_item': self.order_item.pk, 'quantity': 1}],
            },
        }, self.user)
        sales_return = SalesReturn.objects.get(pk=response['server_id'])
        self.assertEqual(sales_return.return_warehouse, self.target)
        self.assertEqual(timezone.localtime(sales_return.created_at).strftime('%Y-%m-%dT%H:%M'), '2026-10-10T14:35')

    def test_sales_user_can_only_edit_own_drafts(self):
        sales_return = self.make_return(completed=False)
        sales = User.objects.create_user(username='return-edit-sales', role='sales')
        self.client.force_login(sales)
        url = reverse('returns:edit', args=[sales_return.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        sales_return.created_by = sales
        sales_return.save(update_fields=['created_by'])
        self.assertEqual(self.client.get(url).status_code, 200)
        approve_sales_return(sales_return=sales_return, user=self.user)
        self.assertEqual(self.client.get(url).status_code, 404)
