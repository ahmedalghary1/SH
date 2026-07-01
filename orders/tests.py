from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from customers.models import Customer
from finance.models import CashAccount, PaymentTransaction
from inventory.models import Stock, StockMovement, Warehouse
from products.models import Category, Color, Product, ProductVariant, Size
from settings_app.models import CompanySettings

from .models import Order, OrderItem
from .services import cancel_order, confirm_order, create_order, get_price_for_customer


class OrderStockServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='manager', password='pass', role='manager')
        category = Category.objects.create(name='تيشيرتات')
        color = Color.objects.create(name='أسود')
        size = Size.objects.create(name='M')
        product = Product.objects.create(
            name='Basic Cotton',
            sku='BC-001',
            category=category,
            retail_price=Decimal('300.00'),
            wholesale_price=Decimal('220.00'),
        )
        self.variant = ProductVariant.objects.create(
            product=product,
            color=color,
            size=size,
            variant_sku='BC-001-BLK-M',
            cost_price=Decimal('120.00'),
        )
        self.warehouse = Warehouse.objects.create(name='المخزن الرئيسي', warehouse_type='main')
        self.customer = Customer.objects.create(name='عميل اختبار', customer_type='b2c', phone='01000000000', created_by=self.user)
        Stock.objects.create(warehouse=self.warehouse, variant=self.variant, quantity=5, min_quantity=1)
        self.order = Order.objects.create(
            order_number='ORD-TEST-001',
            order_type='b2c',
            customer=self.customer,
            warehouse=self.warehouse,
            created_by=self.user,
        )
        OrderItem.objects.create(
            order=self.order,
            variant=self.variant,
            quantity=3,
            unit_price=Decimal('300.00'),
            total=Decimal('900.00'),
        )

    def test_confirm_order_decreases_stock_and_records_sale(self):
        confirm_order(order=self.order, user=self.user)
        stock = Stock.objects.get(warehouse=self.warehouse, variant=self.variant)
        self.order.refresh_from_db()

        self.assertEqual(stock.quantity, 2)
        self.assertEqual(self.order.status, Order.STATUS_CONFIRMED)
        self.assertTrue(StockMovement.objects.filter(movement_type=StockMovement.TYPE_SALE, quantity=3).exists())

    def test_confirm_order_rejects_unavailable_quantity(self):
        self.order.items.update(quantity=8, total=Decimal('2400.00'))

        with self.assertRaises(ValidationError):
            confirm_order(order=self.order, user=self.user)

        stock = Stock.objects.get(warehouse=self.warehouse, variant=self.variant)
        self.assertEqual(stock.quantity, 5)

    def test_cancel_confirmed_order_returns_stock(self):
        confirm_order(order=self.order, user=self.user)
        cancel_order(order=self.order, user=self.user)
        stock = Stock.objects.get(warehouse=self.warehouse, variant=self.variant)
        self.order.refresh_from_db()

        self.assertEqual(stock.quantity, 5)
        self.assertEqual(self.order.status, Order.STATUS_CANCELLED)
        self.assertTrue(StockMovement.objects.filter(movement_type=StockMovement.TYPE_RETURN, quantity=3).exists())

    def test_create_order_stores_cost_and_profit_snapshot(self):
        CashAccount.objects.create(name='Main Cash', balance=Decimal('0.00'))

        order = create_order(
            order_data={
                'order_type': Order.TYPE_B2C,
                'customer': self.customer,
                'warehouse': self.warehouse,
                'payment_method': Order.METHOD_CASH,
                'discount': Decimal('20.00'),
            },
            items=[{
                'variant': self.variant,
                'quantity': 2,
                'unit_price': Decimal('300.00'),
                'discount': Decimal('10.00'),
            }],
            user=self.user,
        )
        item = order.items.get()

        self.assertEqual(item.unit_cost, Decimal('120.00'))
        self.assertEqual(item.cost_total, Decimal('240.00'))
        self.assertEqual(item.profit_total, Decimal('350.00'))
        self.assertEqual(order.total_cost, Decimal('240.00'))
        self.assertEqual(order.gross_profit, Decimal('330.00'))
        self.assertEqual(order.paid_amount, order.total)
        self.assertEqual(order.remaining_amount, Decimal('0'))
        self.assertTrue(PaymentTransaction.objects.filter(related_order=order, amount=Decimal('570.00')).exists())

    def test_create_credit_order_keeps_amount_due_without_auto_payment(self):
        cash = CashAccount.objects.create(name='Credit Test Cash', balance=Decimal('0.00'))

        order = create_order(
            order_data={
                'order_type': Order.TYPE_B2C,
                'customer': self.customer,
                'warehouse': self.warehouse,
                'payment_method': Order.METHOD_CREDIT,
            },
            items=[{
                'variant': self.variant,
                'warehouse': self.warehouse,
                'quantity': 1,
                'unit_price': Decimal('300.00'),
            }],
            user=self.user,
            confirm=True,
        )
        cash.refresh_from_db()

        self.assertEqual(order.payment_method, Order.METHOD_CREDIT)
        self.assertEqual(order.payment_status, Order.PAYMENT_UNPAID)
        self.assertEqual(order.paid_amount, Decimal('0'))
        self.assertEqual(order.remaining_amount, Decimal('300.00'))
        self.assertFalse(PaymentTransaction.objects.filter(related_order=order).exists())
        self.assertEqual(cash.balance, Decimal('0.00'))

    def test_confirm_order_can_deduct_items_from_different_warehouses(self):
        CashAccount.objects.create(name='Multi Warehouse Cash', balance=Decimal('0.00'))
        second_warehouse = Warehouse.objects.create(name='فرع ثاني', warehouse_type=Warehouse.TYPE_MAIN)
        Stock.objects.create(warehouse=second_warehouse, variant=self.variant, quantity=4, min_quantity=1)

        order = create_order(
            order_data={
                'order_type': Order.TYPE_B2C,
                'customer': self.customer,
                'payment_method': Order.METHOD_CASH,
                'discount': Decimal('0.00'),
            },
            items=[
                {
                    'variant': self.variant,
                    'warehouse': self.warehouse,
                    'quantity': 2,
                    'unit_price': Decimal('300.00'),
                    'discount': Decimal('0.00'),
                },
                {
                    'variant': self.variant,
                    'warehouse': second_warehouse,
                    'quantity': 2,
                    'unit_price': Decimal('300.00'),
                    'discount': Decimal('0.00'),
                },
            ],
            user=self.user,
            confirm=True,
        )

        self.assertEqual(order.items.filter(warehouse=self.warehouse).count(), 1)
        self.assertEqual(order.items.filter(warehouse=second_warehouse).count(), 1)
        self.assertEqual(Stock.objects.get(warehouse=self.warehouse, variant=self.variant).quantity, 3)
        self.assertEqual(Stock.objects.get(warehouse=second_warehouse, variant=self.variant).quantity, 2)
        self.assertEqual(order.warehouse, self.warehouse)

    def test_cancel_paid_order_refunds_cash_automatically(self):
        cash = CashAccount.get_default()
        order = create_order(
            order_data={
                'order_type': Order.TYPE_B2C,
                'customer': self.customer,
                'warehouse': self.warehouse,
                'payment_method': Order.METHOD_CASH,
            },
            items=[{
                'variant': self.variant,
                'warehouse': self.warehouse,
                'quantity': 1,
                'unit_price': Decimal('300.00'),
            }],
            user=self.user,
            confirm=True,
        )
        cash.refresh_from_db()
        self.assertEqual(cash.balance, Decimal('300.00'))

        cancel_order(order=order, user=self.user)
        cash.refresh_from_db()

        self.assertEqual(cash.balance, Decimal('0.00'))
        self.assertTrue(PaymentTransaction.objects.filter(
            related_order=order,
            transaction_type=PaymentTransaction.TYPE_REFUND,
            amount=Decimal('300.00'),
        ).exists())

    def test_warehouse_or_sales_rep_shows_sales_rep_for_representative_warehouse(self):
        sales_rep = User.objects.create_user(username='rep-user', password='pass', role=User.ROLE_SALES)
        rep_warehouse = Warehouse.objects.create(
            name='عهدة مندوب',
            warehouse_type=Warehouse.TYPE_REPRESENTATIVE,
            assigned_user=sales_rep,
        )
        order = Order.objects.create(
            order_number='ORD-REP-002',
            order_type='b2c',
            customer=self.customer,
            warehouse=rep_warehouse,
            created_by=sales_rep,
        )
        item = OrderItem.objects.create(
            order=order,
            variant=self.variant,
            warehouse=rep_warehouse,
            quantity=1,
            unit_price=Decimal('300.00'),
            total=Decimal('300.00'),
        )

        self.assertEqual(item.warehouse_or_sales_rep, sales_rep)


class OrderSalesRepProductVisibilityTests(TestCase):
    def setUp(self):
        self.sales = User.objects.create_user(username='rep-order', password='pass', role=User.ROLE_SALES)
        self.manager = User.objects.create_user(username='manager-order', password='pass', role=User.ROLE_MANAGER)
        self.rep_warehouse = Warehouse.objects.create(
            name='Rep Stock',
            warehouse_type=Warehouse.TYPE_REPRESENTATIVE,
            assigned_user=self.sales,
        )
        self.main_warehouse = Warehouse.objects.create(name='Main Stock', warehouse_type=Warehouse.TYPE_MAIN)
        self.other_rep_warehouse = Warehouse.objects.create(
            name='Other Rep Stock',
            warehouse_type=Warehouse.TYPE_REPRESENTATIVE,
        )
        self.visible_product = Product.objects.create(name='Visible Shirt', sku='VIS-001')
        self.hidden_product = Product.objects.create(name='Hidden Shirt', sku='HID-001')
        self.zero_product = Product.objects.create(name='Zero Shirt', sku='ZERO-001')
        self.visible_variant = ProductVariant.objects.create(
            product=self.visible_product,
            variant_sku='VIS-001-BLK-M',
            sale_price=Decimal('300.00'),
        )
        self.hidden_variant = ProductVariant.objects.create(
            product=self.hidden_product,
            variant_sku='HID-001-BLK-M',
            sale_price=Decimal('300.00'),
        )
        self.zero_variant = ProductVariant.objects.create(
            product=self.zero_product,
            variant_sku='ZERO-001-BLK-M',
            sale_price=Decimal('300.00'),
        )
        self.same_product_hidden_variant = ProductVariant.objects.create(
            product=self.visible_product,
            variant_sku='VIS-001-WHT-L',
            sale_price=Decimal('300.00'),
        )
        Stock.objects.create(warehouse=self.rep_warehouse, variant=self.visible_variant, quantity=4, min_quantity=1)
        Stock.objects.create(warehouse=self.main_warehouse, variant=self.hidden_variant, quantity=8, min_quantity=1)
        Stock.objects.create(warehouse=self.rep_warehouse, variant=self.zero_variant, quantity=0, min_quantity=1)
        Stock.objects.create(warehouse=self.other_rep_warehouse, variant=self.same_product_hidden_variant, quantity=5, min_quantity=1)

    def test_sales_rep_product_search_only_returns_products_in_their_stock(self):
        self.client.force_login(self.sales)

        response = self.client.get(reverse('orders:ajax_search_products'), {'q': 'Shirt'})
        product_ids = {row['id'] for row in response.json()['data']}

        self.assertEqual(product_ids, {self.visible_product.id})

    def test_sales_rep_variants_only_returns_variants_in_their_stock(self):
        self.client.force_login(self.sales)

        response = self.client.get(reverse('orders:ajax_get_product_variants', args=[self.visible_product.id]))
        variant_ids = {row['id'] for row in response.json()['data']}

        self.assertEqual(variant_ids, {self.visible_variant.id})

    def test_sales_rep_cannot_fetch_price_for_unavailable_variant(self):
        self.client.force_login(self.sales)

        response = self.client.get(reverse('orders:ajax_get_variant_price', args=[self.hidden_variant.id]))

        self.assertEqual(response.status_code, 404)

    def test_manager_product_search_is_not_restricted_to_rep_stock(self):
        self.client.force_login(self.manager)

        response = self.client.get(reverse('orders:ajax_search_products'), {'q': 'Shirt'})
        product_ids = {row['id'] for row in response.json()['data']}

        self.assertEqual(product_ids, {self.visible_product.id, self.hidden_product.id, self.zero_product.id})


class OrderCreateViewTests(TestCase):
    def setUp(self):
        self.sales = User.objects.create_user(username='create-view-sales', password='pass', role=User.ROLE_SALES)
        category = Category.objects.create(name='Create View Category')
        color = Color.objects.create(name='Black')
        size = Size.objects.create(name='M')
        product = Product.objects.create(
            name='Create View Shirt',
            sku='CV-001',
            category=category,
            retail_price=Decimal('300.00'),
            wholesale_price=Decimal('220.00'),
        )
        self.variant = ProductVariant.objects.create(
            product=product,
            color=color,
            size=size,
            variant_sku='CV-001-BLK-M',
            cost_price=Decimal('120.00'),
            sale_price=Decimal('300.00'),
        )
        self.warehouse = Warehouse.objects.create(
            name='Create View Warehouse',
            warehouse_type=Warehouse.TYPE_REPRESENTATIVE,
            assigned_user=self.sales,
        )
        Stock.objects.create(warehouse=self.warehouse, variant=self.variant, quantity=5, min_quantity=1)

    def test_create_order_view_accepts_items_json_from_invoice_page(self):
        self.client.force_login(self.sales)

        response = self.client.post(reverse('orders:create'), {
            'document_type': Order.DOCUMENT_SALE,
            'order_type': Order.TYPE_B2C,
            'warehouse': str(self.warehouse.id),
            'payment_method': Order.METHOD_CASH,
            'discount_amount': '0',
            'discount_percentage': '0',
            'items_json': (
                f'[{{"variant_id":"{self.variant.id}","warehouse_id":"{self.warehouse.id}",'
                '"quantity":1,"unit_price":"300.00","discount_amount":0,"discount_percentage":0}}]'
            ),
            'action': 'draft',
        })

        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(order.items.get().variant, self.variant)
        self.assertEqual(order.document_type, Order.DOCUMENT_SALE)
        self.assertEqual(order.status, Order.STATUS_DRAFT)
        self.assertEqual(order.payment_status, Order.PAYMENT_UNPAID)
        self.assertFalse(PaymentTransaction.objects.filter(related_order=order).exists())

    def test_new_invoice_action_suspends_current_invoice(self):
        self.client.force_login(self.sales)

        response = self.client.post(reverse('orders:create'), {
            'document_type': Order.DOCUMENT_SALE,
            'order_type': Order.TYPE_B2C,
            'warehouse': str(self.warehouse.id),
            'payment_method': Order.METHOD_CASH,
            'discount_amount': '0',
            'discount_percentage': '0',
            'items_json': (
                f'[{{"variant_id":"{self.variant.id}","warehouse_id":"{self.warehouse.id}",'
                '"quantity":1,"unit_price":"300.00","discount_amount":0,"discount_percentage":0}}]'
            ),
            'action': 'new_invoice',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('orders:create'))
        order = Order.objects.get()
        self.assertEqual(order.status, Order.STATUS_DRAFT)
        self.assertEqual(order.items.count(), 1)
        self.assertFalse(PaymentTransaction.objects.filter(related_order=order).exists())

    def test_create_order_page_exposes_and_saves_discount_percentage(self):
        self.client.force_login(self.sales)

        response = self.client.get(reverse('orders:create'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="discount_percentage"')
        self.assertContains(response, 'id="id_discount_percentage"')
        self.assertContains(response, 'name="document_type"')
        self.assertNotContains(response, 'discount-percentage-input')
        self.assertNotContains(response, 'نوع البيع')
        self.assertNotContains(response, 'خزنة الدفع')
        self.assertNotContains(response, 'ملاحظات داخلية')

        response = self.client.post(reverse('orders:create'), {
            'document_type': Order.DOCUMENT_SALE,
            'order_type': Order.TYPE_B2C,
            'warehouse': str(self.warehouse.id),
            'payment_method': Order.METHOD_CASH,
            'discount_amount': '0',
            'discount_percentage': '10',
            'items_json': (
                f'[{{"variant_id":"{self.variant.id}","warehouse_id":"{self.warehouse.id}",'
                '"quantity":1,"unit_price":"300.00","discount_amount":0,"discount_percentage":0}}]'
            ),
            'action': 'draft',
        })

        self.assertEqual(response.status_code, 302)
        order = Order.objects.latest('pk')
        self.assertEqual(order.discount_percentage, Decimal('10.00'))
        self.assertEqual(order.discount_amount, Decimal('30.00'))
        self.assertEqual(order.total, Decimal('270.00'))


class OrderListViewTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username='list-manager', password='pass', role=User.ROLE_MANAGER)
        self.sale_order = Order.objects.create(
            order_number='ORD-LIST-SALE',
            document_type=Order.DOCUMENT_SALE,
            order_type=Order.TYPE_B2C,
            status=Order.STATUS_CONFIRMED,
            created_by=self.manager,
        )
        self.quote_order = Order.objects.create(
            order_number='ORD-LIST-QUOTE',
            document_type=Order.DOCUMENT_QUOTE,
            order_type=Order.TYPE_B2C,
            created_by=self.manager,
        )

    def test_invoice_list_only_shows_sale_documents_and_hides_quote_buttons(self):
        self.client.force_login(self.manager)

        response = self.client.get(reverse('orders:list'), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.sale_order.order_number)
        self.assertNotContains(response, self.quote_order.order_number)
        self.assertNotContains(response, 'عروض الأسعار')
        self.assertNotContains(response, 'href="/orders/create/?document=quote"')

    def test_quote_list_only_shows_quote_documents(self):
        self.client.force_login(self.manager)

        response = self.client.get(reverse('orders:quote_list'), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.quote_order.order_number)
        self.assertNotContains(response, self.sale_order.order_number)
        self.assertContains(response, 'href="/orders/create/?document=quote"')


class OrderDiscountPolicyTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username='discount-manager', password='pass', role=User.ROLE_MANAGER)
        self.sales = User.objects.create_user(username='discount-sales', password='pass', role=User.ROLE_SALES)
        self.warehouse = Warehouse.objects.create(name='Discount Warehouse', warehouse_type=Warehouse.TYPE_MAIN)
        product = Product.objects.create(
            name='Discount Shirt',
            sku='DISC-001',
            retail_price=Decimal('300.00'),
            wholesale_price=Decimal('220.00'),
        )
        self.variant = ProductVariant.objects.create(
            product=product,
            variant_sku='DISC-001-BLK-M',
            cost_price=Decimal('200.00'),
            sale_price=Decimal('300.00'),
        )
        Stock.objects.create(warehouse=self.warehouse, variant=self.variant, quantity=20, min_quantity=1)
        self.retail_customer = Customer.objects.create(name='Retail Customer', customer_type=Customer.TYPE_RETAIL, phone='01010000001')
        self.b2c_customer = Customer.objects.create(name='B2C Customer', customer_type=Customer.TYPE_B2C, phone='01010000002')
        self.wholesale_customer = Customer.objects.create(name='Wholesale Customer', customer_type=Customer.TYPE_WHOLESALE, phone='01010000003')
        self.b2b_customer = Customer.objects.create(name='B2B Customer', customer_type=Customer.TYPE_B2B, phone='01010000004')
        CompanySettings.load()

    def _create(self, *, user=None, customer=None, order_discount_amount=0, order_discount_percentage=0, item_discount_amount=0, item_discount_percentage=0, unit_price=None):
        customer = customer or self.retail_customer
        return create_order(
            order_data={
                'order_type': Order.TYPE_B2B if customer.customer_type in {Customer.TYPE_B2B, Customer.TYPE_WHOLESALE} else Order.TYPE_B2C,
                'customer': customer,
                'warehouse': self.warehouse,
                'payment_method': Order.METHOD_CASH,
                'paid_amount': Decimal('0.00'),
                'discount_amount': Decimal(str(order_discount_amount)),
                'discount_percentage': Decimal(str(order_discount_percentage)),
                'discount_reason': 'Promo',
            },
            items=[{
                'variant': self.variant,
                'quantity': 2,
                'unit_price': unit_price,
                'discount_amount': Decimal(str(item_discount_amount)),
                'discount_percentage': Decimal(str(item_discount_percentage)),
            }],
            user=user or self.sales,
        )

    def test_price_selection_by_customer_type(self):
        self.assertEqual(get_price_for_customer(self.variant, customer=self.retail_customer), Decimal('300.00'))
        self.assertEqual(get_price_for_customer(self.variant, customer=self.b2c_customer), Decimal('300.00'))
        self.assertEqual(get_price_for_customer(self.variant, customer=self.wholesale_customer), Decimal('300.00'))
        self.assertEqual(get_price_for_customer(self.variant, customer=self.b2b_customer), Decimal('300.00'))

    def test_item_and_order_discounts_update_totals_and_profit(self):
        order = self._create(
            customer=self.retail_customer,
            item_discount_amount=Decimal('10.00'),
            item_discount_percentage=Decimal('5.00'),
            order_discount_amount=Decimal('20.00'),
        )
        item = order.items.get()

        self.assertEqual(item.original_unit_price, Decimal('300.00'))
        self.assertEqual(item.discount, Decimal('40.00'))
        self.assertEqual(item.final_unit_price, Decimal('280.00'))
        self.assertEqual(item.total, Decimal('560.00'))
        self.assertEqual(order.discount_amount, Decimal('20.00'))
        self.assertEqual(order.total, Decimal('540.00'))
        self.assertEqual(order.gross_profit, Decimal('140.00'))
        self.assertEqual(order.discount_approved_by, self.sales)

    def test_rejects_discount_percentage_greater_than_100(self):
        with self.assertRaises(ValidationError):
            self._create(item_discount_percentage=Decimal('101.00'))

    def test_rejects_negative_discount_amount(self):
        with self.assertRaises(ValidationError):
            self._create(item_discount_amount=Decimal('-1.00'))

    def test_rejects_discount_above_sales_limit_even_when_split(self):
        with self.assertRaises(ValidationError):
            self._create(item_discount_percentage=Decimal('6.00'), order_discount_percentage=Decimal('6.00'))

    def test_rejects_sales_below_cost(self):
        with self.assertRaises(ValidationError):
            self._create(unit_price=Decimal('190.00'))

    def test_manager_can_sell_below_cost_when_allowed(self):
        settings = CompanySettings.load()
        settings.allow_manager_sell_below_cost = True
        settings.save(update_fields=['allow_manager_sell_below_cost'])

        order = self._create(user=self.manager, unit_price=Decimal('190.00'))
        item = order.items.get()

        self.assertEqual(item.final_unit_price, Decimal('190.00'))
        self.assertEqual(item.profit_total, Decimal('-20.00'))
