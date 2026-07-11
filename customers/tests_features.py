from io import BytesIO
from datetime import date

from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from accounts.models import User
from customers.models import Customer


class CustomerFeatureTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username='customer-manager', password='x', role=User.ROLE_MANAGER)
        self.customer = Customer.objects.create(name='عميل الاختبار', address='القاهرة المعادي', opening_balance=100, created_by=self.manager)
        self.client.force_login(self.manager)

    def test_search_includes_address(self):
        response = self.client.get(reverse('customers:list'), {'q': 'المعادي'})
        self.assertContains(response, self.customer.name)

    def test_statement_exports_real_xlsx(self):
        response = self.client.get(reverse('customers:statement_export', args=[self.customer.pk, 'xlsx']))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b'PK'))
        self.assertEqual(response['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        workbook = load_workbook(BytesIO(response.content), read_only=True)
        sheet = workbook.active
        values = [cell.value for row in sheet.iter_rows() for cell in row]
        header_row = next(row for row in sheet.iter_rows() if row[0].value == 'التاريخ')
        first_data_cell = sheet.cell(header_row[0].row + 1, 1)
        self.assertIsInstance(first_data_cell.value, date)
        self.assertEqual(first_data_cell.number_format, 'dd/mm/yyyy')
        self.assertIn('عليه', values)
        self.assertIn('له', values)
        self.assertNotIn('المدين', values)
        self.assertNotIn('الدائن', values)
