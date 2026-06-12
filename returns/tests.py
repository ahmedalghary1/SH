from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from customers.models import Customer
from finance.models import CashAccount, PaymentTransaction
from invoices.models import Invoice
from inventory.models import Stock, StockMovement, Warehouse
from orders.models import Order, OrderItem
from products.models import Product, ProductVariant

from .models import SalesReturn, SalesReturnItem
from .forms import SalesReturnCreateForm
from .services import (
    add_exchange_item,
    add_return_item,
    approve_sales_return,
    complete_sales_return,
    create_sales_return,
)


class SalesReturnServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='manager', password='pass', role=User.ROLE_MANAGER)
        self.customer = Customer.objects.create(name='Return Customer', customer_type='b2c', phone='01000000022', created_by=self.user)
        self.warehouse = Warehouse.objects.create(name='Main Warehouse', warehouse_type=Warehouse.TYPE_MAIN)
        product = Product.objects.create(
            name='Cotton Shirt',
            sku='RET-001',
            retail_price=Decimal('300.00'),
            wholesale_price=Decimal('220.00'),
        )
        exchange_product = Product.objects.create(
            name='Premium Shirt',
            sku='RET-002',
            retail_price=Decimal('380.00'),
            wholesale_price=Decimal('280.00'),
        )
        self.variant = ProductVariant.objects.create(product=product, variant_sku='RET-001-BLK-M', cost_price=Decimal('120.00'))
        self.exchange_variant = ProductVariant.objects.create(product=exchange_product, variant_sku='RET-002-WHT-M', cost_price=Decimal('160.00'))
        self.order = Order.objects.create(
            order_number='ORD-RET-001',
            order_type=Order.TYPE_B2C,
            customer=self.customer,
            warehouse=self.warehouse,
            status=Order.STATUS_COMPLETED,
            total=Decimal('900.00'),
            paid_amount=Decimal('900.00'),
            remaining_amount=Decimal('0.00'),
            created_by=self.user,
        )
        self.order_item = OrderItem.objects.create(
            order=self.order,
            variant=self.variant,
            quantity=3,
            unit_price=Decimal('300.00'),
            unit_cost=Decimal('120.00'),
            total=Decimal('900.00'),
            cost_total=Decimal('360.00'),
            profit_total=Decimal('540.00'),
        )
        self.invoice = Invoice.objects.create(order=self.order, invoice_number='INV-RET-001')
        Stock.objects.create(warehouse=self.warehouse, variant=self.variant, quantity=0, min_quantity=0)
        Stock.objects.create(warehouse=self.warehouse, variant=self.exchange_variant, quantity=5, min_quantity=0)
        self.cash = CashAccount.objects.create(name='Main Cash', balance=Decimal('2000.00'))

    def _completed_return(self, quantity=1, condition=SalesReturnItem.CONDITION_GOOD, return_to_stock=True):
        sales_return = create_sales_return(
            order=self.order,
            return_type=SalesReturn.TYPE_PARTIAL_RETURN,
            reason='Size issue',
            user=self.user,
        )
        add_return_item(
            sales_return=sales_return,
            original_order_item=self.order_item,
            quantity=quantity,
            condition=condition,
            return_to_stock=return_to_stock,
        )
        approve_sales_return(sales_return=sales_return, user=self.user)
        complete_sales_return(sales_return=sales_return, user=self.user, cash_account=self.cash)
        return sales_return

    def test_partial_return_adds_good_item_to_stock_and_records_refund(self):
        sales_return = self._completed_return(quantity=1)
        stock = Stock.objects.get(warehouse=self.warehouse, variant=self.variant)
        self.order.refresh_from_db()
        self.cash.refresh_from_db()
        sales_return.refresh_from_db()

        self.assertEqual(stock.quantity, 1)
        self.assertEqual(sales_return.refund_amount, Decimal('300.00'))
        self.assertEqual(self.order.status, Order.STATUS_PARTIALLY_RETURNED)
        self.assertEqual(self.cash.balance, Decimal('1700.00'))
        self.assertTrue(StockMovement.objects.filter(movement_type=StockMovement.TYPE_SALES_RETURN, quantity=1).exists())
        self.assertTrue(PaymentTransaction.objects.filter(transaction_type=PaymentTransaction.TYPE_REFUND, amount=Decimal('300.00')).exists())

    def test_return_rejects_quantity_greater_than_sold(self):
        sales_return = create_sales_return(
            order=self.order,
            return_type=SalesReturn.TYPE_PARTIAL_RETURN,
            reason='Too many',
            user=self.user,
        )

        with self.assertRaises(ValidationError):
            add_return_item(sales_return=sales_return, original_order_item=self.order_item, quantity=4)

    def test_return_rejects_quantity_already_returned(self):
        self._completed_return(quantity=3)
        second_return = create_sales_return(
            order=self.order,
            return_type=SalesReturn.TYPE_PARTIAL_RETURN,
            reason='Duplicate',
            user=self.user,
        )

        with self.assertRaises(ValidationError):
            add_return_item(sales_return=second_return, original_order_item=self.order_item, quantity=1)

    def test_damaged_return_does_not_increase_available_stock(self):
        self._completed_return(quantity=1, condition=SalesReturnItem.CONDITION_DAMAGED, return_to_stock=False)
        stock = Stock.objects.get(warehouse=self.warehouse, variant=self.variant)

        self.assertEqual(stock.quantity, 0)
        self.assertTrue(StockMovement.objects.filter(movement_type=StockMovement.TYPE_DAMAGED_RETURN, quantity=1).exists())

    def test_full_return_sets_order_returned(self):
        self._completed_return(quantity=3)
        self.order.refresh_from_db()

        self.assertEqual(self.order.status, Order.STATUS_RETURNED)

    def test_complete_return_without_cash_account_deducts_default_cash(self):
        default_cash = CashAccount.get_default()
        default_cash.balance = Decimal('1000.00')
        default_cash.save(update_fields=['balance'])
        sales_return = create_sales_return(
            order=self.order,
            return_type=SalesReturn.TYPE_PARTIAL_RETURN,
            reason='Auto refund',
            user=self.user,
        )
        add_return_item(sales_return=sales_return, original_order_item=self.order_item, quantity=1)
        approve_sales_return(sales_return=sales_return, user=self.user)

        complete_sales_return(sales_return=sales_return, user=self.user)
        default_cash.refresh_from_db()

        self.assertEqual(default_cash.balance, Decimal('700.00'))
        self.assertTrue(PaymentTransaction.objects.filter(
            related_order=self.order,
            transaction_type=PaymentTransaction.TYPE_REFUND,
            amount=Decimal('300.00'),
        ).exists())

    def test_exchange_with_company_favor_records_collection_and_moves_stock(self):
        sales_return = create_sales_return(order=self.order, return_type=SalesReturn.TYPE_EXCHANGE, reason='Exchange', user=self.user)
        add_return_item(sales_return=sales_return, original_order_item=self.order_item, quantity=1)
        add_exchange_item(
            sales_return=sales_return,
            old_order_item=self.order_item,
            new_product_variant=self.exchange_variant,
            quantity=1,
            new_unit_price=Decimal('380.00'),
        )
        approve_sales_return(sales_return=sales_return, user=self.user)
        complete_sales_return(sales_return=sales_return, user=self.user, cash_account=self.cash)
        exchange_stock = Stock.objects.get(warehouse=self.warehouse, variant=self.exchange_variant)
        old_stock = Stock.objects.get(warehouse=self.warehouse, variant=self.variant)
        self.cash.refresh_from_db()

        self.assertEqual(exchange_stock.quantity, 4)
        self.assertEqual(old_stock.quantity, 1)
        self.assertEqual(self.cash.balance, Decimal('2080.00'))
        self.assertTrue(PaymentTransaction.objects.filter(transaction_type=PaymentTransaction.TYPE_CUSTOMER_PAYMENT, amount=Decimal('80.00')).exists())

    def test_exchange_rejects_unavailable_new_stock(self):
        Stock.objects.filter(warehouse=self.warehouse, variant=self.exchange_variant).update(quantity=0)
        sales_return = create_sales_return(order=self.order, return_type=SalesReturn.TYPE_EXCHANGE, reason='Exchange', user=self.user)
        add_return_item(sales_return=sales_return, original_order_item=self.order_item, quantity=1)
        add_exchange_item(
            sales_return=sales_return,
            old_order_item=self.order_item,
            new_product_variant=self.exchange_variant,
            quantity=1,
            new_unit_price=Decimal('380.00'),
        )
        approve_sales_return(sales_return=sales_return, user=self.user)

        with self.assertRaises(ValidationError):
            complete_sales_return(sales_return=sales_return, user=self.user, cash_account=self.cash)

    def test_exchange_rejects_new_quantity_greater_than_returned_quantity(self):
        sales_return = create_sales_return(order=self.order, return_type=SalesReturn.TYPE_EXCHANGE, reason='Exchange', user=self.user)
        add_return_item(sales_return=sales_return, original_order_item=self.order_item, quantity=1)

        with self.assertRaises(ValidationError):
            add_exchange_item(
                sales_return=sales_return,
                old_order_item=self.order_item,
                new_product_variant=self.exchange_variant,
                quantity=2,
                new_unit_price=Decimal('380.00'),
            )

    def test_exchange_requires_new_items_before_approval(self):
        sales_return = create_sales_return(order=self.order, return_type=SalesReturn.TYPE_EXCHANGE, reason='Exchange', user=self.user)
        add_return_item(sales_return=sales_return, original_order_item=self.order_item, quantity=1)

        with self.assertRaises(ValidationError):
            approve_sales_return(sales_return=sales_return, user=self.user)

    def test_exchange_with_customer_favor_records_refund_difference(self):
        sales_return = create_sales_return(order=self.order, return_type=SalesReturn.TYPE_EXCHANGE, reason='Exchange', user=self.user)
        add_return_item(sales_return=sales_return, original_order_item=self.order_item, quantity=1)
        add_exchange_item(
            sales_return=sales_return,
            old_order_item=self.order_item,
            new_product_variant=self.exchange_variant,
            quantity=1,
            new_unit_price=Decimal('250.00'),
        )
        approve_sales_return(sales_return=sales_return, user=self.user)
        complete_sales_return(sales_return=sales_return, user=self.user, cash_account=self.cash)
        self.cash.refresh_from_db()

        self.assertEqual(self.cash.balance, Decimal('1950.00'))
        self.assertTrue(PaymentTransaction.objects.filter(transaction_type=PaymentTransaction.TYPE_REFUND, amount=Decimal('50.00')).exists())

    def test_create_form_finds_order_by_invoice_number(self):
        form = SalesReturnCreateForm(
            data={'invoice_number': self.invoice.invoice_number, 'return_type': SalesReturn.TYPE_PARTIAL_RETURN},
            user=self.user,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.order, self.order)

    def test_create_view_displays_invoice_items_after_search(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('returns:create'), data={'invoice_number': self.invoice.invoice_number})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.order.order_number)
        self.assertContains(response, self.variant.product.name)
        self.assertContains(response, f'selected_{self.order_item.pk}')

    def test_create_view_records_selected_invoice_items(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse('returns:create'), data={
            'invoice_number': self.invoice.invoice_number,
            'return_type': SalesReturn.TYPE_PARTIAL_RETURN,
            'reason': 'Size issue',
            f'selected_{self.order_item.pk}': 'on',
            f'quantity_{self.order_item.pk}': '2',
            f'condition_{self.order_item.pk}': SalesReturnItem.CONDITION_GOOD,
            f'return_to_stock_{self.order_item.pk}': 'on',
        })

        sales_return = SalesReturn.objects.latest('pk')
        self.assertRedirects(response, reverse('returns:detail', kwargs={'pk': sales_return.pk}))
        self.assertEqual(sales_return.order, self.order)
        self.assertEqual(sales_return.items.count(), 1)
        self.assertEqual(sales_return.items.first().quantity, 2)

    def test_simple_return_view_displays_and_records_selected_items(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('returns:simple_create'), data={'invoice_number': self.invoice.invoice_number})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.order.order_number)
        self.assertContains(response, f'selected_{self.order_item.pk}')
        self.assertContains(response, 'name="reason"')
        self.assertNotContains(response, 'customer_search')
        self.assertNotContains(response, 'advanced-options')

        response = self.client.post(reverse('returns:simple_create'), data={
            'invoice_number': self.invoice.invoice_number,
            'return_type': SalesReturn.TYPE_PARTIAL_RETURN,
            'reason': 'Simple return',
            f'selected_{self.order_item.pk}': 'on',
            f'quantity_{self.order_item.pk}': '1',
            f'condition_{self.order_item.pk}': SalesReturnItem.CONDITION_GOOD,
            f'return_to_stock_{self.order_item.pk}': 'on',
        })

        sales_return = SalesReturn.objects.latest('pk')
        self.assertRedirects(response, reverse('returns:detail', kwargs={'pk': sales_return.pk}))
        self.assertEqual(sales_return.items.first().quantity, 1)

    def test_simple_exchange_view_displays_and_records_exchange_items(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('returns:simple_exchange'), data={'invoice_number': self.invoice.invoice_number})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.order.order_number)
        self.assertContains(response, self.exchange_variant.product.name)

        response = self.client.post(reverse('returns:simple_exchange'), data={
            'invoice_number': self.invoice.invoice_number,
            'return_type': SalesReturn.TYPE_EXCHANGE,
            'reason': 'Simple exchange',
            f'selected_{self.order_item.pk}': 'on',
            f'quantity_{self.order_item.pk}': '1',
            'new_product_variant_0': str(self.exchange_variant.pk),
            'new_quantity_0': '1',
            'new_price_0': '380.00',
        })

        sales_return = SalesReturn.objects.latest('pk')
        self.assertRedirects(response, reverse('returns:detail', kwargs={'pk': sales_return.pk}))
        self.assertEqual(sales_return.items.count(), 1)
        self.assertEqual(sales_return.exchange_items.count(), 1)
