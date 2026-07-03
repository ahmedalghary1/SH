from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from finance.models import CashAccount
from finance.services import add_expense


class DashboardViewTests(TestCase):
    def test_manager_homepage_shows_requested_quick_actions(self):
        user = User.objects.create_user(username='manager', password='pass', role=User.ROLE_MANAGER)
        self.client.force_login(user)

        response = self.client.get(reverse('dashboard:index'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'شراء بضاعة')
        self.assertContains(response, 'قبض')
        self.assertContains(response, 'مصروف')
        self.assertContains(response, 'عرض سعر')
        self.assertContains(response, 'الخزنة')
        self.assertContains(response, 'العملاء')
        self.assertNotContains(response, 'إضافة عميل')
        self.assertNotContains(response, 'إضافة منتج')

    def test_manager_homepage_shows_today_expenses(self):
        user = User.objects.create_user(username='manager', password='pass', role=User.ROLE_MANAGER)
        cash = CashAccount.objects.create(name='Main Cash', balance=Decimal('1000.00'))
        add_expense(amount=Decimal('125.00'), cash_account=cash, user=user)
        self.client.force_login(user)

        response = self.client.get(reverse('dashboard:index'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'مصروفات اليوم')
        self.assertContains(response, '125.00')
