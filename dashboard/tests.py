from django.test import TestCase
from django.urls import reverse

from accounts.models import User


class DashboardViewTests(TestCase):
    def test_manager_homepage_shows_requested_quick_actions(self):
        user = User.objects.create_user(username='manager', password='pass', role=User.ROLE_MANAGER)
        self.client.force_login(user)

        response = self.client.get(reverse('dashboard:index'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'شراء بضاعة')
        self.assertContains(response, 'قبض')
        self.assertContains(response, 'عرض سعر')
        self.assertContains(response, 'الخزنة')
        self.assertContains(response, 'العملاء')
        self.assertNotContains(response, 'إضافة عميل')
        self.assertNotContains(response, 'إضافة منتج')
