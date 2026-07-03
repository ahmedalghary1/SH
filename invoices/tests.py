from decimal import Decimal
from datetime import date

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from customers.models import Customer
from finance.models import CashAccount, PaymentTransaction
from inventory.models import Warehouse
from orders.models import Order, OrderItem
from products.models import Product, ProductVariant
from settings_app.models import CompanySettings

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

    def test_generate_invoice_does_not_auto_collect_credit_invoice(self):
        credit_order = Order.objects.create(
            order_number='ORD-CREDIT-001',
            order_type=Order.TYPE_B2C,
            customer=self.order.customer,
            warehouse=self.order.warehouse,
            status=Order.STATUS_CONFIRMED,
            payment_method=Order.METHOD_CREDIT,
            payment_status=Order.PAYMENT_UNPAID,
            subtotal=Decimal('500.00'),
            total=Decimal('500.00'),
            paid_amount=Decimal('0.00'),
            remaining_amount=Decimal('500.00'),
            created_by=self.user,
        )

        invoice = generate_invoice(credit_order, user=self.user)
        credit_order.refresh_from_db()

        self.assertEqual(invoice.order, credit_order)
        self.assertEqual(credit_order.payment_status, Order.PAYMENT_UNPAID)
        self.assertEqual(credit_order.remaining_amount, Decimal('500.00'))
        self.assertFalse(PaymentTransaction.objects.filter(related_order=credit_order).exists())

    def test_invoice_payment_add_records_installment_date_and_remaining_amount(self):
        self.client.login(username='manager', password='pass12345')
        cash = CashAccount.objects.create(name='Invoice Installment Cash', balance=Decimal('0.00'))
        credit_order = Order.objects.create(
            order_number='ORD-CREDIT-PAY-001',
            order_type=Order.TYPE_B2C,
            customer=self.order.customer,
            warehouse=self.order.warehouse,
            status=Order.STATUS_CONFIRMED,
            payment_method=Order.METHOD_CREDIT,
            payment_status=Order.PAYMENT_UNPAID,
            subtotal=Decimal('500.00'),
            total=Decimal('500.00'),
            paid_amount=Decimal('0.00'),
            remaining_amount=Decimal('500.00'),
            created_by=self.user,
        )
        invoice = Invoice.objects.create(order=credit_order, invoice_number='INV-CREDIT-PAY-001')

        response = self.client.post(reverse('invoices:payment_add', kwargs={'pk': invoice.pk}), {
            'cash_account': cash.pk,
            'amount': '200.00',
            'transaction_date': '2026-06-01',
            'notes': 'first installment',
        })
        credit_order.refresh_from_db()
        cash.refresh_from_db()
        tx = PaymentTransaction.objects.get(related_order=credit_order)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(credit_order.payment_status, Order.PAYMENT_PARTIAL)
        self.assertEqual(credit_order.paid_amount, Decimal('200.00'))
        self.assertEqual(credit_order.remaining_amount, Decimal('300.00'))
        self.assertEqual(cash.balance, Decimal('200.00'))
        self.assertEqual(tx.transaction_date, date(2026, 6, 1))

    def test_invoice_payment_add_accepts_negative_amount(self):
        self.client.login(username='manager', password='pass12345')
        cash = CashAccount.objects.create(name='Invoice Refund Cash', balance=Decimal('300.00'))
        credit_order = Order.objects.create(
            order_number='ORD-CREDIT-REFUND-001',
            order_type=Order.TYPE_B2C,
            customer=self.order.customer,
            warehouse=self.order.warehouse,
            status=Order.STATUS_CONFIRMED,
            payment_method=Order.METHOD_CREDIT,
            payment_status=Order.PAYMENT_PARTIAL,
            subtotal=Decimal('500.00'),
            total=Decimal('500.00'),
            paid_amount=Decimal('200.00'),
            remaining_amount=Decimal('300.00'),
            created_by=self.user,
        )
        invoice = Invoice.objects.create(order=credit_order, invoice_number='INV-CREDIT-REFUND-001')

        response = self.client.post(reverse('invoices:payment_add', kwargs={'pk': invoice.pk}), {
            'cash_account': cash.pk,
            'amount': '-50.00',
            'transaction_date': '2026-06-01',
            'notes': 'refund installment',
        })
        credit_order.refresh_from_db()
        cash.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(credit_order.paid_amount, Decimal('150.00'))
        self.assertEqual(credit_order.remaining_amount, Decimal('350.00'))
        self.assertEqual(cash.balance, Decimal('250.00'))
        self.assertTrue(PaymentTransaction.objects.filter(
            related_order=credit_order,
            transaction_type=PaymentTransaction.TYPE_REFUND,
            direction=PaymentTransaction.DIRECTION_OUT,
            amount=Decimal('50.00'),
        ).exists())

    def test_invoice_payment_add_stores_overpayment_as_customer_credit(self):
        self.client.login(username='manager', password='pass12345')
        cash = CashAccount.objects.create(name='Invoice Overpay Cash', balance=Decimal('0.00'))
        credit_order = Order.objects.create(
            order_number='ORD-CREDIT-OVERPAY-001',
            order_type=Order.TYPE_B2C,
            customer=self.order.customer,
            warehouse=self.order.warehouse,
            status=Order.STATUS_CONFIRMED,
            payment_method=Order.METHOD_CREDIT,
            payment_status=Order.PAYMENT_UNPAID,
            subtotal=Decimal('500.00'),
            total=Decimal('500.00'),
            paid_amount=Decimal('0.00'),
            remaining_amount=Decimal('500.00'),
            created_by=self.user,
        )
        invoice = Invoice.objects.create(order=credit_order, invoice_number='INV-CREDIT-OVERPAY-001')

        response = self.client.post(reverse('invoices:payment_add', kwargs={'pk': invoice.pk}), {
            'cash_account': cash.pk,
            'amount': '600.00',
            'transaction_date': '2026-06-01',
            'notes': 'overpayment',
        })
        credit_order.refresh_from_db()
        credit_order.customer.refresh_from_db()
        cash.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(credit_order.paid_amount, Decimal('500.00'))
        self.assertEqual(credit_order.remaining_amount, Decimal('0.00'))
        self.assertEqual(credit_order.customer.opening_balance, Decimal('-100.00'))
        self.assertEqual(cash.balance, Decimal('600.00'))
        self.assertTrue(PaymentTransaction.objects.filter(
            related_order=credit_order,
            transaction_type=PaymentTransaction.TYPE_CUSTOMER_PAYMENT,
            amount=Decimal('500.00'),
        ).exists())
        self.assertTrue(PaymentTransaction.objects.filter(
            related_order__isnull=True,
            related_customer=credit_order.customer,
            transaction_type=PaymentTransaction.TYPE_CUSTOMER_PAYMENT,
            amount=Decimal('100.00'),
        ).exists())

    def test_invoice_detail_uses_table_and_print_uses_thermal_receipt(self):
        self.client.force_login(self.user)

        detail_response = self.client.get(reverse('invoices:detail', kwargs={'pk': self.invoice.pk}), secure=True)
        print_response = self.client.get(reverse('invoices:print', kwargs={'pk': self.invoice.pk}), secure=True)

        self.assertContains(detail_response, 'screen-invoice')
        self.assertContains(detail_response, 'invoice-items-table')
        self.assertNotContains(detail_response, 'receipt-invoice')
        self.assertContains(print_response, 'receipt-invoice')
        self.assertContains(print_response, 'receipt-items-table')
        self.assertContains(print_response, 'كود المنتج: PDF-TEST-001')
        self.assertContains(print_response, '--media-width: 80mm')
        self.assertContains(print_response, '--paper-width: 72mm')
        self.assertContains(print_response, 'size: 72mm auto')
        self.assertContains(print_response, '--receipt-width: 66mm')
        self.assertContains(print_response, '--receipt-vertical-padding: 10mm')
        self.assertContains(print_response, '--receipt-font-scale: 1.15')
        self.assertContains(print_response, '--receipt-font-body: 9.2px')
        self.assertContains(print_response, 'text-align: center')
        self.assertContains(print_response, 'grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr)')
        self.assertContains(print_response, 'font-weight: 900')
        self.assertNotContains(print_response, 'app-shell')
        self.assertNotContains(print_response, 'css/main.css')

    def test_invoice_print_uses_configured_thermal_paper_width(self):
        self.client.force_login(self.user)
        settings = CompanySettings.load()
        settings.thermal_paper_width = CompanySettings.THERMAL_WIDTH_58
        settings.save(update_fields=['thermal_paper_width'])

        response = self.client.get(reverse('invoices:print', kwargs={'pk': self.invoice.pk}), secure=True)

        self.assertContains(response, '--media-width: 58mm')
        self.assertContains(response, '--paper-width: 58mm')
        self.assertContains(response, 'size: 58mm auto')
        self.assertContains(response, '--receipt-width: 50mm')

    def test_invoice_print_uses_configured_font_scale(self):
        self.client.force_login(self.user)
        settings = CompanySettings.load()
        settings.thermal_invoice_font_scale = CompanySettings.THERMAL_FONT_XLARGE
        settings.save(update_fields=['thermal_invoice_font_scale'])

        response = self.client.get(reverse('invoices:print', kwargs={'pk': self.invoice.pk}), secure=True)

        self.assertContains(response, '--receipt-font-scale: 1.3')
        self.assertContains(response, '--receipt-font-body: 10.4px')
        self.assertContains(response, '--receipt-font-table: 7.4px')

    def test_invoice_print_exposes_direct_print_settings(self):
        self.client.force_login(self.user)
        settings = CompanySettings.load()
        settings.thermal_print_mode = CompanySettings.PRINT_MODE_ELECTRON
        settings.thermal_printer_name = 'POS-80'
        settings.save(update_fields=['thermal_print_mode', 'thermal_printer_name'])

        response = self.client.get(reverse('invoices:print', kwargs={'pk': self.invoice.pk}), secure=True)

        self.assertContains(response, 'const printMode = "electron"')
        self.assertContains(response, 'const printerName = "POS-80"')
        self.assertContains(response, 'const printableWidth = 72')
        self.assertContains(response, 'const receiptWidth = 66')
        self.assertContains(response, 'pageHeight')
        self.assertContains(response, 'window.shDesktopPrinter')
        self.assertContains(response, 'qz.websocket')

    def test_invoice_print_count_is_marked_by_post_not_page_open(self):
        self.client.force_login(self.user)

        self.client.get(reverse('invoices:print', kwargs={'pk': self.invoice.pk}), secure=True)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.printed_count, 0)

        response = self.client.post(reverse('invoices:print_mark', kwargs={'pk': self.invoice.pk}), secure=True)
        self.invoice.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.invoice.printed_count, 1)
