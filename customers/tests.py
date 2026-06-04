from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from finance.models import CashAccount, PaymentTransaction
from orders.models import Order
from returns.models import SalesReturn

from .models import Customer, CustomerInteraction
from .services import (
    get_customer_complaints_count,
    get_customer_last_interaction,
    get_customer_last_order,
    get_customer_return_rate,
    get_customer_total_paid,
    get_customer_total_purchases,
    get_customer_total_remaining,
    get_customers_with_debt,
    get_due_followups,
    get_inactive_customers,
    get_top_customers,
)


class CustomerCRMServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='sales', password='pass', role=User.ROLE_SALES)
        self.customer = Customer.objects.create(
            name='CRM Customer',
            customer_type=Customer.TYPE_RETAIL,
            phone='01000000055',
            opening_balance=Decimal('50.00'),
            credit_limit=Decimal('1000.00'),
            created_by=self.user,
        )
        self.cash = CashAccount.objects.create(name='CRM Cash', balance=Decimal('0.00'))
        self.order = Order.objects.create(
            order_number='ORD-CRM-001',
            order_type=Order.TYPE_B2C,
            customer=self.customer,
            status=Order.STATUS_COMPLETED,
            total=Decimal('500.00'),
            paid_amount=Decimal('200.00'),
            remaining_amount=Decimal('300.00'),
            created_by=self.user,
        )
        PaymentTransaction.objects.create(
            transaction_type=PaymentTransaction.TYPE_CUSTOMER_PAYMENT,
            direction=PaymentTransaction.DIRECTION_IN,
            amount=Decimal('200.00'),
            cash_account=self.cash,
            related_order=self.order,
            related_customer=self.customer,
            created_by=self.user,
        )

    def test_customer_financial_metrics_use_orders_and_transactions_once(self):
        self.assertEqual(get_customer_total_purchases(self.customer), Decimal('500.00'))
        self.assertEqual(get_customer_total_paid(self.customer), Decimal('200.00'))
        self.assertEqual(get_customer_total_remaining(self.customer), Decimal('350.00'))

    def test_last_order_and_interaction_helpers(self):
        interaction = CustomerInteraction.objects.create(
            customer=self.customer,
            interaction_type=CustomerInteraction.TYPE_CALL,
            title='Call after delivery',
            created_by=self.user,
        )

        self.assertEqual(get_customer_last_order(self.customer), self.order)
        self.assertEqual(get_customer_last_interaction(self.customer), interaction)

    def test_due_followups_and_complaints_report(self):
        due = CustomerInteraction.objects.create(
            customer=self.customer,
            interaction_type=CustomerInteraction.TYPE_FOLLOW_UP,
            title='Due follow up',
            next_follow_up_date=timezone.localdate(),
            created_by=self.user,
        )
        CustomerInteraction.objects.create(
            customer=self.customer,
            interaction_type=CustomerInteraction.TYPE_COMPLAINT,
            title='Open complaint',
            created_by=self.user,
        )

        self.assertIn(due, list(get_due_followups()))
        self.assertEqual(get_customer_complaints_count(self.customer), 1)

    def test_inactive_debtors_top_customers_and_return_rate(self):
        old_customer = Customer.objects.create(name='Old Customer', customer_type=Customer.TYPE_RETAIL, phone='01000000056', created_by=self.user)
        old_order = Order.objects.create(
            order_number='ORD-CRM-OLD',
            order_type=Order.TYPE_B2C,
            customer=old_customer,
            status=Order.STATUS_COMPLETED,
            total=Decimal('100.00'),
            remaining_amount=Decimal('0.00'),
            created_by=self.user,
        )
        Order.objects.filter(pk=old_order.pk).update(created_at=timezone.now() - timedelta(days=120))
        SalesReturn.objects.create(
            order=self.order,
            customer=self.customer,
            status=SalesReturn.STATUS_COMPLETED,
            return_type=SalesReturn.TYPE_PARTIAL_RETURN,
            refund_amount=Decimal('100.00'),
            created_by=self.user,
        )

        self.assertIn(old_customer, list(get_inactive_customers(days=90)))
        self.assertIn(self.customer, list(get_customers_with_debt()))
        self.assertEqual(list(get_top_customers(1))[0], self.customer)
        self.assertEqual(get_customer_return_rate(self.customer), Decimal('100'))


class CustomerCRMViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='sales', password='pass', role=User.ROLE_SALES)
        self.customer = Customer.objects.create(name='View Customer', customer_type=Customer.TYPE_RETAIL, phone='01000000057', created_by=self.user)
        self.client.force_login(self.user)

    def test_create_edit_and_complete_interaction_flow(self):
        create_url = reverse('customers:interaction_create', kwargs={'pk': self.customer.pk})
        response = self.client.post(create_url, {
            'interaction_type': CustomerInteraction.TYPE_FOLLOW_UP,
            'title': 'First follow up',
            'description': 'Call customer',
            'next_follow_up_date': timezone.localdate(),
            'is_completed': '',
        })
        self.assertRedirects(response, reverse('customers:crm_detail', kwargs={'pk': self.customer.pk}))
        interaction = CustomerInteraction.objects.get(customer=self.customer)
        self.assertEqual(interaction.created_by, self.user)

        edit_url = reverse('customers:interaction_edit', kwargs={'pk': self.customer.pk, 'interaction_id': interaction.pk})
        response = self.client.post(edit_url, {
            'interaction_type': CustomerInteraction.TYPE_WHATSAPP,
            'title': 'WhatsApp follow up',
            'description': 'Updated',
            'next_follow_up_date': timezone.localdate(),
            'is_completed': '',
        })
        self.assertRedirects(response, reverse('customers:crm_detail', kwargs={'pk': self.customer.pk}))
        interaction.refresh_from_db()
        self.assertEqual(interaction.interaction_type, CustomerInteraction.TYPE_WHATSAPP)

        complete_url = reverse('customers:interaction_complete', kwargs={'pk': self.customer.pk, 'interaction_id': interaction.pk})
        response = self.client.post(complete_url)
        self.assertRedirects(response, reverse('customers:crm_detail', kwargs={'pk': self.customer.pk}))
        interaction.refresh_from_db()
        self.assertTrue(interaction.is_completed)

    def test_crm_pages_open_for_sales_role(self):
        urls = [
            reverse('customers:crm'),
            reverse('customers:crm_detail', kwargs={'pk': self.customer.pk}),
            reverse('customers:interactions_today'),
            reverse('customers:report_top_customers'),
            reverse('customers:report_inactive'),
            reverse('customers:report_debtors'),
            reverse('customers:report_complaints'),
        ]

        for url in urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
