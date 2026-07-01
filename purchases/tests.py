import json
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from finance.models import CashAccount, PaymentTransaction
from inventory.models import Stock, StockMovement, Warehouse
from products.models import Category, Color, Product, ProductVariant, Size

from .models import PurchaseOrder, Supplier
from .raw_material import record_raw_material_purchase
from .services import create_purchase_order, pay_supplier, receive_purchase_order_items


class PurchaseServiceTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username='manager', password='pass', role=User.ROLE_MANAGER)
        self.supplier = Supplier.objects.create(name='Fabric Supplier')
        product = Product.objects.create(
            name='Cotton Shirt',
            sku='SH-PUR-001',
            retail_price=Decimal('300.00'),
            wholesale_price=Decimal('220.00'),
        )
        self.variant = ProductVariant.objects.create(
            product=product,
            variant_sku='SH-PUR-001-BLK-M',
            cost_price=Decimal('90.00'),
        )
        self.warehouse = Warehouse.objects.create(name='Main Warehouse', warehouse_type=Warehouse.TYPE_MAIN)
        self.cash = CashAccount.objects.create(name='Main Cash', balance=Decimal('10000.00'))

    def create_order(self):
        return create_purchase_order(
            supplier=self.supplier,
            items=[{
                'product_variant': self.variant,
                'quantity': 10,
                'unit_cost': Decimal('125.00'),
            }],
            user=self.manager,
        )

    def test_create_purchase_order_calculates_totals_and_supplier_due(self):
        po = self.create_order()
        self.supplier.refresh_from_db()

        self.assertEqual(po.total_amount, Decimal('1250.00'))
        self.assertEqual(po.remaining_amount, Decimal('1250.00'))
        self.assertEqual(self.supplier.current_balance, Decimal('1250.00'))

    def test_receive_partial_purchase_increases_stock_and_records_movement(self):
        po = self.create_order()
        item = po.items.get()

        receive_purchase_order_items(
            purchase_order=po,
            warehouse=self.warehouse,
            received_items={item.pk: 4},
            user=self.manager,
        )
        item.refresh_from_db()
        po.refresh_from_db()
        self.variant.refresh_from_db()
        stock = Stock.objects.get(warehouse=self.warehouse, variant=self.variant)

        self.assertEqual(stock.quantity, 4)
        self.assertEqual(item.received_quantity, 4)
        self.assertEqual(po.status, PurchaseOrder.STATUS_PARTIALLY_RECEIVED)
        self.assertEqual(self.variant.cost_price, Decimal('125.00'))
        self.assertTrue(StockMovement.objects.filter(movement_type=StockMovement.TYPE_PURCHASE_RECEIVE, quantity=4).exists())

    def test_receive_full_purchase_sets_received_status(self):
        po = self.create_order()
        item = po.items.get()

        receive_purchase_order_items(
            purchase_order=po,
            warehouse=self.warehouse,
            received_items={item.pk: 10},
            user=self.manager,
        )
        po.refresh_from_db()

        self.assertEqual(po.status, PurchaseOrder.STATUS_RECEIVED)

    def test_receive_rejects_quantity_greater_than_ordered(self):
        po = self.create_order()
        item = po.items.get()

        with self.assertRaises(ValidationError):
            receive_purchase_order_items(
                purchase_order=po,
                warehouse=self.warehouse,
                received_items={item.pk: 11},
                user=self.manager,
            )

        self.assertFalse(Stock.objects.filter(warehouse=self.warehouse, variant=self.variant).exists())

    def test_pay_supplier_creates_finance_transaction_and_updates_balances(self):
        po = self.create_order()

        pay_supplier(purchase_order=po, amount=Decimal('500.00'), cash_account=self.cash, user=self.manager)
        po.refresh_from_db()
        self.supplier.refresh_from_db()
        self.cash.refresh_from_db()

        self.assertEqual(po.paid_amount, Decimal('500.00'))
        self.assertEqual(po.remaining_amount, Decimal('750.00'))
        self.assertEqual(self.supplier.current_balance, Decimal('750.00'))
        self.assertEqual(self.cash.balance, Decimal('9500.00'))
        self.assertTrue(PaymentTransaction.objects.filter(related_supplier=self.supplier, amount=Decimal('500.00')).exists())

    def test_pay_supplier_rejects_overpayment(self):
        po = self.create_order()

        with self.assertRaises(ValidationError):
            pay_supplier(purchase_order=po, amount=Decimal('1300.00'), cash_account=self.cash, user=self.manager)

        self.cash.refresh_from_db()
        self.assertEqual(self.cash.balance, Decimal('10000.00'))

    def test_raw_material_purchase_deducts_default_cash_and_links_supplier(self):
        default_cash = CashAccount.get_default()
        default_cash.balance = Decimal('1000.00')
        default_cash.save(update_fields=['balance'])

        record_raw_material_purchase(
            raw_name='Cotton Fabric',
            supplier=self.supplier,
            amount=Decimal('250.00'),
            user=self.manager,
            notes='test buy',
        )
        default_cash.refresh_from_db()

        self.assertEqual(default_cash.balance, Decimal('750.00'))
        self.assertTrue(PaymentTransaction.objects.filter(
            related_supplier=self.supplier,
            amount=Decimal('250.00'),
            notes__icontains='Cotton Fabric',
        ).exists())

    def test_direct_purchase_view_creates_new_product_and_supplier_from_modal_fields(self):
        self.client.force_login(self.manager)
        cash = CashAccount.objects.create(name='Purchase Cash', balance=Decimal('1000.00'))
        warehouse = Warehouse.objects.create(name='Direct Purchase Warehouse', warehouse_type=Warehouse.TYPE_MAIN)

        response = self.client.post(reverse('purchases:order_create'), {
            'supplier': '',
            'new_supplier_name': 'New Modal Supplier',
            'new_supplier_phone': '01012345678',
            'product_variant': '',
            'new_product_name': 'Modal Shirt',
            'new_product_sku': 'MOD-SH-001',
            'new_category': '',
            'new_category_name': 'Modal Category',
            'new_color': '',
            'new_color_name': 'Modal Black',
            'new_size': '',
            'new_size_name': 'M',
            'pieces_per_dozen': '10',
            'retail_price': '300.00',
            'wholesale_price': '220.00',
            'warehouse': warehouse.pk,
            'cash_account': cash.pk,
            'quantity': '2',
            'unit_cost': '100.00',
            'notes': 'modal purchase',
        }, secure=True)

        self.assertEqual(response.status_code, 302)
        supplier = Supplier.objects.get(name='New Modal Supplier')
        product = Product.objects.get(sku='MOD-SH-001')
        variant = ProductVariant.objects.get(product=product)
        cash.refresh_from_db()

        self.assertEqual(product.supplier, supplier)
        self.assertEqual(product.category.name, 'Modal Category')
        self.assertEqual(product.pieces_per_dozen, 10)
        self.assertEqual(variant.color.name, 'Modal Black')
        self.assertEqual(variant.size.name, 'M')
        self.assertEqual(Stock.objects.get(warehouse=warehouse, variant=variant).quantity, 2)
        self.assertEqual(cash.balance, Decimal('800.00'))

    def test_direct_purchase_view_accepts_multiple_items_in_one_invoice(self):
        self.client.force_login(self.manager)
        cash = CashAccount.objects.create(name='Multi Purchase Cash', balance=Decimal('2000.00'))
        warehouse = Warehouse.objects.create(name='Multi Purchase Warehouse', warehouse_type=Warehouse.TYPE_MAIN)
        product = Product.objects.create(name='Purchase Pants', sku='PUR-PANTS-001')
        second_variant = ProductVariant.objects.create(product=product, variant_sku='PUR-PANTS-001-BLU-L')

        response = self.client.post(reverse('purchases:order_create'), {
            'supplier': self.supplier.pk,
            'product_variant': '',
            'warehouse': warehouse.pk,
            'cash_account': cash.pk,
            'quantity': '',
            'unit_cost': '',
            'items_json': json.dumps([
                {'product_variant_id': self.variant.pk, 'quantity': 2, 'unit_cost': '100.00'},
                {'product_variant_id': second_variant.pk, 'quantity': 3, 'unit_cost': '50.00'},
            ]),
            'notes': 'multi item purchase',
        }, secure=True)

        self.assertEqual(response.status_code, 302)
        po = PurchaseOrder.objects.get(notes='multi item purchase')
        cash.refresh_from_db()

        self.assertEqual(po.items.count(), 2)
        self.assertEqual(po.total_amount, Decimal('350.00'))
        self.assertEqual(po.status, PurchaseOrder.STATUS_RECEIVED)
        self.assertEqual(Stock.objects.get(warehouse=warehouse, variant=self.variant).quantity, 2)
        self.assertEqual(Stock.objects.get(warehouse=warehouse, variant=second_variant).quantity, 3)
        self.assertEqual(cash.balance, Decimal('1650.00'))

    def test_purchase_quick_product_ajax_creates_variant_without_warehouse(self):
        self.client.force_login(self.manager)
        supplier = Supplier.objects.create(name='Quick Product Supplier')
        category = Category.objects.create(name='Quick Category')
        color = Color.objects.create(name='Quick Black')
        size = Size.objects.create(name='Quick M')

        response = self.client.post(reverse('purchases:ajax_quick_create_purchase_product'), {
            'supplier': supplier.pk,
            'new_product_name': 'Quick Purchase Shirt',
            'new_product_sku': 'QP-SH-001',
            'new_category': category.pk,
            'new_color': color.pk,
            'new_size': size.pk,
            'pieces_per_dozen': '8',
            'retail_price': '320.00',
            'wholesale_price': '240.00',
            'unit_cost': '110.00',
        }, secure=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['success'])
        variant = ProductVariant.objects.get(pk=payload['data']['id'])

        self.assertEqual(variant.product.supplier, supplier)
        self.assertEqual(variant.product.pieces_per_dozen, 8)
        self.assertEqual(variant.cost_price, Decimal('110.00'))
        self.assertEqual(variant.retail_price, Decimal('320.00'))
        self.assertFalse(Stock.objects.filter(variant=variant).exists())

    def test_purchase_quick_supplier_ajax_creates_and_returns_option_data(self):
        self.client.force_login(self.manager)

        response = self.client.post(reverse('purchases:ajax_quick_create_purchase_supplier'), {
            'new_supplier_name': 'Quick Supplier',
            'new_supplier_phone': '01000000000',
        }, secure=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['success'])
        supplier = Supplier.objects.get(pk=payload['data']['id'])
        self.assertEqual(supplier.name, 'Quick Supplier')

    def test_purchase_return_supplier_variants_ajax_filters_by_supplier_and_stock(self):
        self.client.force_login(self.manager)
        supplier = Supplier.objects.create(name='Return Supplier')
        other_supplier = Supplier.objects.create(name='Other Return Supplier')
        category = Category.objects.create(name='Return Category')
        color = Color.objects.create(name='Return Black')
        size = Size.objects.create(name='Return M')
        warehouse = Warehouse.objects.create(name='Return Warehouse', warehouse_type=Warehouse.TYPE_MAIN)
        product = Product.objects.create(name='Return Product', sku='RET-001', supplier=supplier, category=category)
        variant = ProductVariant.objects.create(product=product, color=color, size=size, variant_sku='RET-001-BLK-M')
        other_product = Product.objects.create(name='Other Return Product', sku='RET-002', supplier=other_supplier, category=category)
        other_variant = ProductVariant.objects.create(product=other_product, color=color, size=size, variant_sku='RET-002-BLK-M')
        Stock.objects.create(warehouse=warehouse, variant=variant, quantity=5)
        Stock.objects.create(warehouse=warehouse, variant=other_variant, quantity=7)

        response = self.client.get(
            reverse('purchases:ajax_supplier_product_variants'),
            {'supplier_id': supplier.pk},
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        variants = response.json()['data']['variants']
        self.assertEqual([item['id'] for item in variants], [variant.pk])
        self.assertEqual(variants[0]['available_quantity'], 5)

    def test_purchase_return_rejects_variant_from_another_supplier(self):
        self.client.force_login(self.manager)
        supplier = Supplier.objects.create(name='Correct Supplier')
        other_supplier = Supplier.objects.create(name='Wrong Supplier')
        category = Category.objects.create(name='Return Validation Category')
        color = Color.objects.create(name='Return Validation Black')
        size = Size.objects.create(name='Return Validation M')
        warehouse = Warehouse.objects.create(name='Return Validation Warehouse', warehouse_type=Warehouse.TYPE_MAIN)
        product = Product.objects.create(name='Wrong Supplier Product', sku='RET-WRONG-001', supplier=other_supplier, category=category)
        variant = ProductVariant.objects.create(product=product, color=color, size=size, variant_sku='RET-WRONG-001-BLK-M')
        Stock.objects.create(warehouse=warehouse, variant=variant, quantity=5)

        response = self.client.post(reverse('purchases:purchase_return'), {
            'supplier': supplier.pk,
            'product_variant': variant.pk,
            'warehouse': warehouse.pk,
            'quantity': '1',
            'unit_cost': '10.00',
            'notes': '',
        }, secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'اختر صنفا خاصا بالمورد المحدد')
