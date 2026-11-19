from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from accounts.models import User
from inventory.models import Stock, Warehouse
from inventory.services import stock_in, sale_stock, transfer_stock, return_stock
from products.models import Product, ProductVariant
from reports.services import movement_balance_rows


class MovementBalanceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='movement-manager', role='manager')
        self.source = Warehouse.objects.create(name='Source')
        self.target = Warehouse.objects.create(name='Target')
        product = Product.objects.create(name='Product', sku='BALANCE')
        self.variant = ProductVariant.objects.create(product=product, variant_sku='BALANCE-V')
        # Legacy opening stock has no movement record.
        Stock.objects.create(warehouse=self.source, variant=self.variant, quantity=5)
        self.incoming = stock_in(variant=self.variant, warehouse=self.source, quantity=10, user=self.user)
        self.sale = sale_stock(variant=self.variant, warehouse=self.source, quantity=3, user=self.user)
        self.transfer = transfer_stock(variant=self.variant, from_warehouse=self.source,
                                       to_warehouse=self.target, quantity=4, user=self.user)
        self.returned = return_stock(variant=self.variant, warehouse=self.source, quantity=2, user=self.user)

    def test_hidden_later_movements_do_not_change_historical_sale_balance(self):
        rows = movement_balance_rows([self.sale], self.source.pk)
        self.assertEqual([(r.previous_balance, r.current_balance) for r in rows], [(15, 12)])

    def test_transfer_has_separate_balances_for_both_warehouses(self):
        rows = movement_balance_rows([self.transfer])
        self.assertEqual([(r.report_warehouse.pk, r.previous_balance, r.current_balance) for r in rows],
                         [(self.source.pk, 12, 8), (self.target.pk, 0, 4)])

    def test_report_filters_dates_and_types_without_resetting_balance(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('inventory:product_movements', args=[self.variant.product_id]), {'warehouse': self.source.pk, 'movement_type': 'sale'})
        self.assertEqual(response.status_code, 200)
        row = response.context['movements'][0]
        self.assertEqual((row.previous_balance, row.current_balance), (15, 12))
        self.assertContains(response, 'رصيد سابق')
        self.assertContains(response, 'الرصيد بعد الحركة')

    def test_report_groups_all_variants_and_warehouses_once_per_product(self):
        second = ProductVariant.objects.create(product=self.variant.product, variant_sku='BALANCE-SECOND')
        stock_in(variant=second, warehouse=self.source, quantity=7, user=self.user)
        self.client.force_login(self.user)
        response = self.client.get(reverse('reports:stock_movement'))
        rows = list(response.context['products'])
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['movement_count'], rows[0]['incoming'], rows[0]['outgoing'], rows[0]['current_balance']), (5, 23, 7, 21))
        detail = self.client.get(rows[0]['detail_url'])
        self.assertEqual(len(detail.context['movements']), 6)  # Both transfer legs.

    def test_summary_preserves_warehouse_and_type_filters_in_detail_link(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('reports:stock_movement'), {'warehouse': self.source.pk, 'movement_type': 'sale'})
        row = response.context['products'][0]
        self.assertEqual((row['incoming'], row['outgoing'], row['current_balance']), (0, 3, 10))
        detail = self.client.get(row['detail_url'])
        self.assertEqual([movement.pk for movement in detail.context['movements']], [self.sale.pk])

    def test_summary_and_details_include_history_beyond_500_events(self):
        from inventory.models import StockMovement
        StockMovement.objects.bulk_create([StockMovement(variant=self.variant, to_warehouse=self.source,
            quantity=1, movement_type='in', created_by=self.user) for _ in range(505)])
        self.client.force_login(self.user)
        response = self.client.get(reverse('reports:stock_movement'))
        self.assertEqual(response.context['products'][0]['movement_count'], 509)
        detail = self.client.get(reverse('inventory:product_movements', args=[self.variant.product_id]), {'page': 11})
        self.assertEqual(len(detail.context['movements']), 510)  # Both transfer legs, even on an old page link.
        self.assertNotContains(detail, 'class="pagination"')

    def test_invalid_warehouse_does_not_expose_all_movements(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('reports:stock_movement'), {'warehouse': 'bad'})
        self.assertFalse(response.context['products'])

    def test_equal_timestamps_have_deterministic_order(self):
        from inventory.models import StockMovement
        stamp = timezone.now() - timedelta(days=1)
        StockMovement.objects.update(created_at=stamp)
        rows = movement_balance_rows([self.incoming, self.sale, self.transfer, self.returned], self.source.pk)
        self.assertEqual([r.pk for r in rows], [self.returned.pk, self.transfer.pk, self.sale.pk, self.incoming.pk])
        self.assertEqual(rows[-1].previous_balance, 5)
