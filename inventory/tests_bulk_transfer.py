from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from inventory.forms import BulkStockTransferForm
from inventory.models import Stock, StockBatch, StockMovement, Warehouse
from inventory.services import stock_in, transfer_stock_bulk
from products.models import Product, ProductVariant
from sync_api.services import process_operation


class BulkTransferTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='bulk-manager', role='manager')
        self.source = Warehouse.objects.create(name='Source', warehouse_type='main')
        self.target = Warehouse.objects.create(name='Target', warehouse_type='store')
        product = Product.objects.create(name='Transfer product', sku='BULK')
        self.variants = [ProductVariant.objects.create(product=product, variant_sku=f'BULK-{i}') for i in range(2)]
        for variant in self.variants:
            stock_in(variant=variant, warehouse=self.source, quantity=10, unit_cost=7, user=self.user)
        self.data = {'from_warehouse': self.source.pk, 'to_warehouse': self.target.pk,
                     'items-TOTAL_FORMS': '2', 'items-INITIAL_FORMS': '0',
                     'items-0-variant': self.variants[0].pk, 'items-0-quantity': '3',
                     'items-1-variant': self.variants[1].pk, 'items-1-quantity': '4'}

    def transfer(self, quantities):
        return transfer_stock_bulk(items=[{'variant': v, 'quantity': q} for v, q in zip(self.variants, quantities)],
                                   from_warehouse=self.source, to_warehouse=self.target, user=self.user)

    def test_view_transfers_all_lines_and_preserves_cost(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('inventory:transfer'), self.data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(list(Stock.objects.filter(warehouse=self.target).order_by('variant_id').values_list('quantity', flat=True)), [3, 4])
        self.assertEqual(list(StockBatch.objects.filter(warehouse=self.target).values_list('unit_cost', flat=True)), [7, 7])

    def test_last_line_failure_rolls_back_stock_batches_and_movements(self):
        with self.assertRaises(ValidationError):
            self.transfer([3, 11])
        self.assertFalse(Stock.objects.filter(warehouse=self.target).exists())
        self.assertFalse(StockMovement.objects.filter(movement_type='transfer').exists())
        self.assertEqual(list(StockBatch.objects.values_list('remaining_quantity', flat=True)), [10, 10])

    def test_duplicate_lines_are_summed_before_checking_stock(self):
        with self.assertRaises(ValidationError):
            transfer_stock_bulk(items=[{'variant': self.variants[0], 'quantity': 6}] * 2,
                                from_warehouse=self.source, to_warehouse=self.target, user=self.user)
        self.assertEqual(Stock.objects.get(warehouse=self.source, variant=self.variants[0]).quantity, 10)

    def test_empty_deleted_fractional_and_same_warehouse_inputs(self):
        for changes in [{'items-0-quantity': '1.5'}, {'items-0-quantity': '-2'},
                        {'to_warehouse': self.source.pk}, {'items-0-DELETE': 'on', 'items-1-DELETE': 'on'},
                        {'items-TOTAL_FORMS': '101'}]:
            with self.subTest(changes=changes):
                self.assertFalse(BulkStockTransferForm({**self.data, **changes}).is_valid())

    def test_offline_transfer_replay_does_not_repeat_any_line(self):
        operation = {'idempotency_key': 'bulk-transfer', 'device_id': 'bulk-device', 'entity_type': 'stock',
                     'operation_type': 'create', 'local_uuid': 'bulk-local',
                     'payload': {'original_url': '/inventory/movements/transfer/', 'stock': self.data}}
        first = process_operation(operation, self.user)
        self.assertEqual(first['status'], 'success', first)
        self.assertEqual(process_operation(operation, self.user), first)
        self.assertEqual(StockMovement.objects.filter(movement_type='transfer').count(), 2)
        self.assertEqual(Stock.objects.get(warehouse=self.source, variant=self.variants[0]).quantity, 7)
