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
        response = self.client.get(reverse('reports:stock_movement'), {'warehouse': self.source.pk, 'movement_type': 'sale'})
        self.assertEqual(response.status_code, 200)
        row = response.context['movements'][0]
        self.assertEqual((row.previous_balance, row.current_balance), (15, 12))
        self.assertContains(response, 'رصيد سابق')
        self.assertContains(response, 'الرصيد الحالي')

    def test_equal_timestamps_have_deterministic_order(self):
        from inventory.models import StockMovement
        stamp = timezone.now() - timedelta(days=1)
        StockMovement.objects.update(created_at=stamp)
        rows = movement_balance_rows([self.incoming, self.sale, self.transfer, self.returned], self.source.pk)
        self.assertEqual([r.pk for r in rows], [self.returned.pk, self.transfer.pk, self.sale.pk, self.incoming.pk])
        self.assertEqual(rows[-1].previous_balance, 5)
