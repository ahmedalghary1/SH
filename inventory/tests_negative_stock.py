import json
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from accounts.models import User
from customers.models import Customer
from inventory.models import Stock, StockBatch, Warehouse
from inventory.services import stock_in, sale_stock, return_stock, adjust_stock
from orders.models import Order
from orders.services import create_order, cancel_order
from products.models import Product, ProductVariant
from products.services import create_representative_product
from purchases.models import Supplier
from purchases.services import create_purchase_order, receive_purchase_order_items
from sync_api.services import process_operation


class NegativeRepresentativeStockTests(TestCase):
    def setUp(self):
        self.rep = User.objects.create_user(username='negative-rep', role='sales')
        self.manager = User.objects.create_user(username='negative-manager', role='manager')
        self.warehouse = Warehouse.objects.create(name='Rep warehouse', warehouse_type='representative', assigned_user=self.rep)
        self.other = Warehouse.objects.create(name='Main', warehouse_type='main')
        self.customer = Customer.objects.create(name='Rep customer', created_by=self.rep)
        product = Product.objects.create(name='Existing', sku='NEG-OLD')
        self.variant = ProductVariant.objects.create(product=product, variant_sku='NEG-OLD-V', cost_price=10, retail_price=30)
        self.product_data = dict(name='New product', sku='NEG-NEW', retail_price='30', wholesale_price='25', cost_price='10')

    def sell(self, quantity, user=None, warehouse=None):
        return sale_stock(variant=self.variant, warehouse=warehouse or self.warehouse, quantity=quantity, user=user or self.rep)

    def purchase(self, quantity):
        supplier = Supplier.objects.create(name='Supplier')
        order = create_purchase_order(supplier=supplier, items=[{'product_variant':self.variant,'quantity':quantity,'unit_cost':12}], user=self.manager)
        item = order.items.get()
        receive_purchase_order_items(purchase_order=order, warehouse=self.warehouse,
                                     received_items={item.pk:quantity}, user=self.manager)

    def test_sale_without_any_stock_row_creates_negative_balance(self):
        movement = self.sell(10)
        self.assertEqual(Stock.objects.get(warehouse=self.warehouse, variant=self.variant).quantity, -10)
        self.assertEqual(movement.consumed_cost_total, Decimal('100'))
        self.assertEqual(StockBatch.objects.get(source='negative_sale').remaining_quantity, 0)

    def test_purchase_receipts_settle_debt_before_available_batches(self):
        self.sell(10)
        self.purchase(6)
        self.assertEqual(Stock.objects.get(warehouse=self.warehouse, variant=self.variant).quantity, -4)
        self.assertEqual(sum(StockBatch.objects.values_list('remaining_quantity', flat=True)), 0)
        self.purchase(9)
        self.assertEqual(Stock.objects.get(warehouse=self.warehouse, variant=self.variant).quantity, 5)
        self.assertEqual(sum(StockBatch.objects.values_list('remaining_quantity', flat=True)), 5)
        self.assertEqual(StockBatch.objects.exclude(source='negative_sale').last().received_quantity, 9)

    def test_returns_and_adjustments_do_not_create_phantom_available_batches(self):
        self.sell(10)
        return_stock(variant=self.variant, warehouse=self.warehouse, quantity=3, user=self.manager)
        self.assertEqual(Stock.objects.get(warehouse=self.warehouse, variant=self.variant).quantity, -7)
        self.assertEqual(sum(StockBatch.objects.values_list('remaining_quantity',flat=True)), 0)
        adjust_stock(variant=self.variant,warehouse=self.warehouse,new_quantity=0,user=self.manager)
        self.assertEqual(sum(StockBatch.objects.values_list('remaining_quantity',flat=True)), 0)

    def test_other_warehouses_and_roles_cannot_sell_negative(self):
        for user, warehouse in [(self.rep,self.other),(self.manager,self.warehouse)]:
            with self.subTest(user=user):
                with self.assertRaises(ValidationError):
                    self.sell(1,user=user,warehouse=warehouse)
        self.assertFalse(Stock.objects.exists())

    def test_quick_creation_has_zero_stock_and_is_immediately_sellable(self):
        product, variant = create_representative_product(data={**self.product_data,'quantity':100,'warehouse':self.other.pk}, user=self.rep)
        self.assertEqual(product.name, 'New product')
        self.assertEqual(Stock.objects.get(variant=variant).quantity,0)
        self.assertEqual(Stock.objects.get(variant=variant).warehouse, self.warehouse)
        sale_stock(variant=variant,warehouse=self.warehouse,quantity=2,user=self.rep)
        self.assertEqual(Stock.objects.get(variant=variant).quantity,-2)

    def test_online_invoice_with_zero_stock_confirms_and_cancels_once(self):
        self.client.force_login(self.rep)
        response=self.client.post(reverse('orders:create'), {
            'document_type':'sale','order_type':'b2c','payment_method':'credit','customer':self.customer.pk,
            'warehouse':self.warehouse.pk,'discount_amount':'0','discount_percentage':'0','action':'confirm',
            'items_json':json.dumps([dict(variant_id=self.variant.pk,warehouse_id=self.warehouse.pk,quantity=7,unit_price='30')])})
        self.assertEqual(response.status_code,302)
        order=Order.objects.get()
        self.assertEqual(Stock.objects.get(variant=self.variant).quantity,-7)
        cancel_order(order=order,user=self.manager)
        self.assertEqual(Stock.objects.get(variant=self.variant).quantity,0)
        self.assertEqual(sum(StockBatch.objects.values_list('remaining_quantity',flat=True)),0)

    def operation(self, key, entity, payload):
        return {'idempotency_key':key,'device_id':'rep-device','entity_type':entity,'operation_type':'create','local_uuid':key,'payload':payload}

    def test_offline_product_then_sale_resolves_local_reference_and_retries_once(self):
        product_op=self.operation('local-product','product',{'original_url':'/products/representative/create/','product':self.product_data})
        product_result=process_operation(product_op,self.rep)
        self.assertEqual(product_result['status'],'success',product_result)
        op=self.operation('local-sale','order',{'order':{'customer_server_id':self.customer.pk,'warehouse':self.warehouse.pk,
                 'document_type':'sale','action':'confirm','payment_method':'credit'},
                 'items':[{'variant_id':'local-variant','product_local_uuid':'local-product','warehouse_id':self.warehouse.pk,'quantity':10,'unit_price':'30'}]})
        sale_result=process_operation(op,self.rep)
        self.assertEqual(sale_result['status'],'success',sale_result)
        self.assertEqual(process_operation(op,self.rep),sale_result)
        self.assertEqual(process_operation(product_op,self.rep),product_result)
        self.assertEqual(Stock.objects.get(variant_id=product_result['variant_id']).quantity,-10)
        self.assertEqual(Order.objects.count(),1)

    def test_rep_cannot_sync_regular_product_edits_or_use_other_users_receipt(self):
        edit=self.operation('forbidden','product',{'original_url':'/products/create/','product':self.product_data})
        self.assertEqual(process_operation(edit,self.rep)['status'],'failed_conflict')
        created=process_operation(self.operation('private-product','product',{'original_url':'/products/representative/create/','product':self.product_data}),self.rep)
        self.assertEqual(created['status'],'success')
        other=User.objects.create_user(username='other-neg-rep',role='sales')
        warehouse=Warehouse.objects.create(name='Other rep',warehouse_type='representative',assigned_user=other)
        customer=Customer.objects.create(name='Other customer',created_by=other)
        op=self.operation('foreign-reference','order',{'order':{'customer_server_id':customer.pk,'warehouse':warehouse.pk,'action':'confirm'},
            'items':[{'product_local_uuid':'private-product','warehouse_id':warehouse.pk,'quantity':1,'unit_price':'30'}]})
        self.assertEqual(process_operation(op,other)['status'],'failed_conflict')
        self.assertFalse(Order.objects.exists())

    def test_transfer_into_negative_custody_settles_debt(self):
        from inventory.services import transfer_stock
        self.sell(10)
        stock_in(variant=self.variant,warehouse=self.other,quantity=12,user=self.manager)
        transfer_stock(variant=self.variant,from_warehouse=self.other,to_warehouse=self.warehouse,quantity=6,user=self.manager)
        self.assertEqual(Stock.objects.get(warehouse=self.warehouse,variant=self.variant).quantity,-4)
        self.assertEqual(sum(StockBatch.objects.filter(warehouse=self.warehouse).values_list('remaining_quantity',flat=True)),0)
        transfer_stock(variant=self.variant,from_warehouse=self.other,to_warehouse=self.warehouse,quantity=6,user=self.manager)
        self.assertEqual(Stock.objects.get(warehouse=self.warehouse,variant=self.variant).quantity,2)
        self.assertEqual(sum(StockBatch.objects.filter(warehouse=self.warehouse).values_list('remaining_quantity',flat=True)),2)

    def test_representative_product_form_creates_online_and_rejects_duplicate_code(self):
        self.client.force_login(self.rep)
        response=self.client.post(reverse('products:representative_create'),self.product_data)
        self.assertEqual(response.status_code,302)
        response=self.client.post(reverse('products:representative_create'),self.product_data)
        self.assertEqual(response.status_code,200)
        self.assertEqual(Product.objects.filter(sku='NEG-NEW').count(),1)
