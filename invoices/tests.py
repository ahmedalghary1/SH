from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from customers.models import Customer
from finance.models import CashAccount, PaymentTransaction
from inventory.models import Warehouse
from orders.models import Order, OrderItem
from products.models import Product, ProductVariant

from .models import Invoice
from .services import generate_invoice


class InvoicePDFExportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='manager',
            password='pass12345',
            role=User.ROLE_MANAGER,
            is_superuser=True,
        )
        customer = Customer.objects.create(
            name='عميل اختبار',
            customer_type=Customer.TYPE_B2C,
            phone='01000000000',
            created_by=self.user,
        )
        warehouse = Warehouse.objects.create(
            name='مخزن اختبار',
            warehouse_type=Warehouse.TYPE_MAIN,
        )
        product = Product.objects.create(
            name='قميص اختبار',
            sku='PDF-TEST-001',
            retail_price=Decimal('250'),
            wholesale_price=Decimal('180'),
        )
        variant = ProductVariant.objects.create(
            product=product,
            variant_sku='PDF-TEST-001-BLK-M',
        )
        self.order = Order.objects.create(
            order_number='ORD-PDF-TEST-001',
            order_type=Order.TYPE_B2C,
            customer=customer,
            warehouse=warehouse,
            status=Order.STATUS_COMPLETED,
            payment_status=Order.PAYMENT_PAID,
            subtotal=Decimal('250'),
            total=Decimal('250'),
            paid_amount=Decimal('250'),
            remaining_amount=Decimal('0'),
            created_by=self.user,
        )
        OrderItem.objects.create(
            order=self.order,
            variant=variant,
            quantity=1,
            unit_price=Decimal('250'),
            total=Decimal('250'),
        )
        self.invoice = Invoice.objects.create(
            order=self.order,
            invoice_number='INV-PDF-TEST-001',
        )

    def test_invoice_report_pdf_download_returns_pdf(self):
        self.client.login(username='manager', password='pass12345')

        response = self.client.post(
            reverse('invoices:export_pdf'),
            {'invoice_ids': [str(self.invoice.pk)]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('invoice-report.pdf', response['Content-Disposition'])
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_generate_invoice_records_sale_in_default_cash_once(self):
        default_cash = CashAccount.get_default()

        invoice = generate_invoice(self.order, user=self.user)
        generate_invoice(self.order, user=self.user)
        default_cash.refresh_from_db()

        self.assertEqual(invoice, self.invoice)
        self.assertEqual(default_cash.balance, Decimal('250.00'))
        self.assertEqual(
            PaymentTransaction.objects.filter(
                related_order=self.order,
                transaction_type=PaymentTransaction.TYPE_CUSTOMER_PAYMENT,
            ).count(),
            1,
        )
