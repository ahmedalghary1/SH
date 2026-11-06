from decimal import Decimal
from datetime import datetime

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User, Branch
from config.branching import set_current_branch, reset_current_branch
from customers.models import Customer
from orders.models import Order, OrderItem

from .models import SalesReturn, SalesReturnItem
from .services import (
    customer_purchase_rows, create_customer_returns,
    approve_sales_return, complete_sales_return,
)
from . import tests as legacy_tests


class CustomerReturnTests(TestCase):
    def setUp(self):
        legacy_tests.SalesReturnServiceTests.setUp(self)
        self.latest = Order.objects.create(
            order_number='ORD-NEW', customer=self.customer,
            warehouse=self.warehouse, order_type=Order.TYPE_B2C,
            status=Order.STATUS_COMPLETED, created_by=self.user,
            total=Decimal('500'), remaining_amount=Decimal('500'),
        )
        self.latest_item = OrderItem.objects.create(
            order=self.latest, variant=self.variant, quantity=2,
            unit_price=Decimal('275'), discount_amount=Decimal('50'),
            total=Decimal('500'),
        )

    def selection(self, quantity=1, variant=None):
        return dict(variant_id=(variant or self.variant).pk, quantity=quantity,
                    condition='good', return_to_stock=True)

    def test_unique_variant_uses_latest_net_price_and_combines_quantities(self):
        rows = customer_purchase_rows(customer=self.customer, user=self.user)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['unit_price'], Decimal('250'))
        self.assertEqual(rows[0]['available_quantity'], 5)
        self.assertEqual(rows[0]['latest_order'], self.latest)

    def test_allocates_newest_first_and_completes_at_latest_price(self):
        drafts = create_customer_returns(customer=self.customer, user=self.user,
                                         selections=[self.selection(4)])
        self.assertEqual(len(drafts), 2)
        items = SalesReturnItem.objects.order_by('pk')
        self.assertEqual(list(items.values_list('original_order_item_id', 'quantity', 'refund_amount')), [
            (self.latest_item.pk, 2, Decimal('500')),
            (self.order_item.pk, 2, Decimal('500')),
        ])
        for draft in drafts:
            approve_sales_return(sales_return=draft, user=self.user)
            complete_sales_return(sales_return=draft, user=self.user, cash_account=self.cash)
        rows = customer_purchase_rows(customer=self.customer, user=self.user)
        self.assertEqual(rows[0]['available_quantity'], 1)
        self.assertEqual(rows[0]['unit_price'], Decimal('250'))
        self.latest.refresh_from_db()
        self.assertEqual(self.latest.remaining_amount, Decimal('0'))

    def test_multiple_products_and_atomic_failure(self):
        OrderItem.objects.create(order=self.latest, variant=self.exchange_variant,
                                 quantity=1, unit_price=380, total=380)
        with self.assertRaises(ValidationError):
            create_customer_returns(customer=self.customer, user=self.user,
                selections=[self.selection(), self.selection(2, self.exchange_variant)])
        self.assertFalse(SalesReturn.objects.exists())
        drafts = create_customer_returns(customer=self.customer, user=self.user,
            selections=[self.selection(), self.selection(1, self.exchange_variant)])
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0].items.count(), 2)

    def test_rejects_other_customers_products_and_bad_quantities(self):
        other = Customer.objects.create(name='Other customer', created_by=self.user)
        for quantity in (0, -1, '1.5', 'NaN', 6):
            with self.subTest(quantity=quantity), self.assertRaises(ValidationError):
                create_customer_returns(customer=self.customer, user=self.user,
                                         selections=[self.selection(quantity)])
        with self.assertRaises(ValidationError):
            create_customer_returns(customer=other, user=self.user,
                                     selections=[self.selection()])
        self.assertFalse(SalesReturn.objects.exists())

    def test_excludes_cancelled_draft_and_quotes_from_latest_price(self):
        for status, document in [(Order.STATUS_CANCELLED, Order.DOCUMENT_SALE),
                                 (Order.STATUS_DRAFT, Order.DOCUMENT_SALE),
                                 (Order.STATUS_COMPLETED, Order.DOCUMENT_QUOTE)]:
            self.latest.status = status
            self.latest.document_type = document
            self.latest.save()
            row = customer_purchase_rows(customer=self.customer, user=self.user)[0]
            self.assertEqual(row['available_quantity'], 3)
            self.assertEqual(row['unit_price'], Decimal('300'))

    def test_sales_user_only_sees_their_orders(self):
        sales = User.objects.create_user(username='sales-return', role=User.ROLE_SALES,
                                         password='pass', branch=self.user.branch)
        self.order.created_by = sales
        self.order.save()
        row = customer_purchase_rows(customer=self.customer, user=sales)[0]
        self.assertEqual(row['unit_price'], Decimal('300'))
        self.assertEqual(row['available_quantity'], 3)
        self.client.force_login(sales)
        response = self.client.get(reverse('returns:customer_create'), {'customer': self.customer.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['item_rows']), 1)

    def test_branch_scope_hides_other_branch_purchases(self):
        branch = Branch.objects.create(name='Other branch', code='OTHER-RET')
        token = set_current_branch(branch.pk)
        try:
            self.assertEqual(customer_purchase_rows(customer=self.customer, user=self.user), [])
            with self.assertRaises(ValidationError):
                create_customer_returns(customer=self.customer, user=self.user,
                                         selections=[self.selection()])
        finally:
            reset_current_branch(token)

    def test_customer_page_and_post_ignore_client_price(self):
        self.client.force_login(self.user)
        url = reverse('returns:customer_create')
        response = self.client.get(url, {'customer': self.customer.pk})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.variant.variant_sku)
        self.assertContains(response, 'purchase-search')
        self.assertEqual(len(response.context['item_rows']), 1)
        response = self.client.post(url, {
            'customer': self.customer.pk,
            f'selected_{self.variant.pk}': 'on', f'quantity_{self.variant.pk}': '1',
            f'return_to_stock_{self.variant.pk}': 'on', 'unit_price': '1',
        })
        draft = SalesReturn.objects.get()
        self.assertRedirects(response, reverse('returns:detail', args=[draft.pk]))
        self.assertEqual(draft.refund_amount, Decimal('250'))

    def test_invalid_post_preserves_selection_and_displays_error(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('returns:customer_create'), {
            'customer': self.customer.pk, f'selected_{self.variant.pk}': 'on',
            f'quantity_{self.variant.pk}': '6',
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].non_field_errors())
        self.assertTrue(response.context['item_rows'][0]['selected'])
        self.assertEqual(response.context['item_rows'][0]['quantity_value'], '6')
        self.assertFalse(SalesReturn.objects.exists())

    def test_dashboard_links_to_customer_returns(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('dashboard:index'))
        self.assertContains(response, reverse('returns:customer_create'))

    def test_empty_selection_and_invalid_condition_do_not_create_drafts(self):
        for selections in ([], [{**self.selection(), 'condition': 'invalid'}]):
            with self.assertRaises(ValidationError):
                create_customer_returns(customer=self.customer, user=self.user,
                                         selections=selections)
        self.assertFalse(SalesReturn.objects.exists())

    def test_selected_datetime_is_saved_on_all_customer_return_drafts(self):
        self.client.force_login(self.user)
        selected = '2026-11-03T14:35'
        response = self.client.post(reverse('returns:customer_create'), {
            'customer': self.customer.pk, 'return_datetime': selected,
            f'selected_{self.variant.pk}': 'on', f'quantity_{self.variant.pk}': '4',
        })
        self.assertRedirects(response, reverse('returns:list'))
        expected = timezone.make_aware(datetime.fromisoformat(selected))
        self.assertEqual(SalesReturn.objects.count(), 2)
        self.assertTrue(all(draft.created_at == expected for draft in SalesReturn.objects.all()))
        response = self.client.get(reverse('returns:list'), {
            'period': 'custom', 'date_from': '2026-11-03', 'date_to': '2026-11-03',
        })
        self.assertEqual(len(response.context['returns']), 2)

    def test_customer_return_date_is_editable_and_initialized_after_search(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('returns:customer_create'), {'customer': self.customer.pk})
        self.assertContains(response, 'name="return_datetime"')
        self.assertContains(response, 'type="datetime-local"')
        self.assertTrue(response.context['form']['return_datetime'].value())
        self.assertNotIn('readonly', response.context['form']['return_datetime'].field.widget.attrs)

    def test_invalid_datetime_keeps_input_and_does_not_create_return(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('returns:customer_create'), {
            'customer': self.customer.pk, 'return_datetime': '2026-02-30T14:35',
            f'selected_{self.variant.pk}': 'on', f'quantity_{self.variant.pk}': '1',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('return_datetime', response.context['form'].errors)
        self.assertEqual(response.context['form']['return_datetime'].value(), '2026-02-30T14:35')
        self.assertTrue(response.context['item_rows'][0]['selected'])
        self.assertFalse(SalesReturn.objects.exists())

    def test_invoice_return_routes_save_selected_datetime(self):
        self.client.force_login(self.user)
        selected = '2026-11-02T10:20'
        for route in ('returns:simple_create', 'returns:create'):
            with self.subTest(route=route):
                response = self.client.post(reverse(route), {
                    'invoice_number': self.invoice.invoice_number,
                    'return_type': SalesReturn.TYPE_PARTIAL_RETURN, 'return_datetime': selected,
                    f'selected_{self.order_item.pk}': 'on', f'quantity_{self.order_item.pk}': '1',
                })
                self.assertEqual(response.status_code, 302)
                self.assertEqual(SalesReturn.objects.latest('pk').created_at,
                                 timezone.make_aware(datetime.fromisoformat(selected)))
