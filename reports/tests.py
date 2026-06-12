from django.test import TestCase
from django.urls import reverse

from accounts.models import User


class ReportPagesTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(
            username='reports-manager',
            password='pass',
            role=User.ROLE_MANAGER,
        )
        self.client.force_login(self.manager)

    def test_report_index_renders(self):
        response = self.client.get(reverse('reports:index'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'التقارير')

    def test_core_report_pages_render_without_data(self):
        report_names = [
            'sales',
            'profitability',
            'net_profit',
            'customer_debt',
            'inactive_customers',
            'discounts',
            'sales_rep_custody',
            'sales_rep_collections',
            'low_stock',
            'stale_products',
            'returns',
            'purchases',
            'supplier_dues',
            'daily_sales',
            'monthly_sales',
            'yearly_sales',
            'inventory',
            'customers',
            'employees',
            'stock_movement',
        ]

        for name in report_names:
            with self.subTest(name=name):
                response = self.client.get(reverse(f'reports:{name}'))
                self.assertEqual(response.status_code, 200)

    def test_sales_report_export_uses_arabic_headers(self):
        response = self.client.get(reverse('reports:sales_export'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'لا توجد بيانات')

    def test_sales_user_sees_only_sales_reports_on_index(self):
        sales = User.objects.create_user(
            username='reports-sales',
            password='pass',
            role=User.ROLE_SALES,
        )
        self.client.force_login(sales)

        response = self.client.get(reverse('reports:index'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'تقرير اليوم')
        self.assertContains(response, 'تقرير المبيعات')
        self.assertContains(response, 'تقرير المرتجعات')
        self.assertNotContains(response, 'تقرير الأرباح')
        self.assertNotContains(response, 'مديونيات الموردين')

    def test_warehouse_user_sees_only_inventory_reports_on_index(self):
        warehouse = User.objects.create_user(
            username='reports-warehouse',
            password='pass',
            role=User.ROLE_WAREHOUSE,
        )
        self.client.force_login(warehouse)

        response = self.client.get(reverse('reports:index'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'تقرير المخزون')
        self.assertContains(response, 'المنتجات الناقصة')
        self.assertContains(response, 'حركة المخزون')
        self.assertNotContains(response, 'تقرير المبيعات')
        self.assertNotContains(response, 'تقرير الأرباح')

    def test_backend_blocks_reports_outside_user_role(self):
        sales = User.objects.create_user(
            username='reports-sales-blocked',
            password='pass',
            role=User.ROLE_SALES,
        )
        warehouse = User.objects.create_user(
            username='reports-warehouse-blocked',
            password='pass',
            role=User.ROLE_WAREHOUSE,
        )

        self.client.force_login(sales)
        response = self.client.get(reverse('reports:profitability'))
        self.assertEqual(response.status_code, 403)

        self.client.force_login(warehouse)
        response = self.client.get(reverse('reports:sales'))
        self.assertEqual(response.status_code, 403)
