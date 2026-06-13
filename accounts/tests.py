from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from .models import User
from .permissions import can_manage_purchases, can_view_costs, has_role
from config.settings import env_bool, env_list


class PermissionHelperTests(SimpleTestCase):
    def test_manager_can_view_costs_and_manage_purchases(self):
        user = User(username='manager', role=User.ROLE_MANAGER)

        self.assertTrue(can_view_costs(user))
        self.assertTrue(can_manage_purchases(user))

    def test_sales_cannot_view_costs(self):
        user = User(username='sales', role=User.ROLE_SALES)

        self.assertFalse(can_view_costs(user))
        self.assertFalse(can_manage_purchases(user))

    def test_superuser_passes_role_checks(self):
        user = User(username='admin', role=User.ROLE_SALES, is_superuser=True)

        self.assertTrue(has_role(user, User.ROLE_WAREHOUSE))


class EnvironmentSettingHelperTests(SimpleTestCase):
    def test_env_bool_parses_common_true_values(self):
        with self.settings():
            import os
            os.environ['ERP_TEST_BOOL'] = 'true'
            self.assertTrue(env_bool('ERP_TEST_BOOL'))
            os.environ.pop('ERP_TEST_BOOL', None)

    def test_env_list_splits_comma_values(self):
        import os
        os.environ['ERP_TEST_LIST'] = 'localhost, example.com,'
        self.assertEqual(env_list('ERP_TEST_LIST'), ['localhost', 'example.com'])
        os.environ.pop('ERP_TEST_LIST', None)

    def test_env_list_uses_default_for_empty_values(self):
        import os
        os.environ['ERP_TEST_EMPTY_LIST'] = ''
        self.assertEqual(env_list('ERP_TEST_EMPTY_LIST', 'example.com'), ['example.com'])
        os.environ.pop('ERP_TEST_EMPTY_LIST', None)


class LoginCsrfCookieTests(TestCase):
    def test_login_page_sets_csrf_cookie(self):
        response = self.client.get(
            reverse('accounts:login'),
            HTTP_HOST='sh.elwsamstore.com',
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('csrftoken', response.cookies)

    def test_login_post_with_csrf_cookie_is_not_rejected(self):
        client = Client(enforce_csrf_checks=True)
        login_url = reverse('accounts:login')
        get_response = client.get(login_url, HTTP_HOST='sh.elwsamstore.com', secure=True)
        csrf_token = get_response.cookies['csrftoken'].value

        response = client.post(
            login_url,
            {
                'username': 'missing-user',
                'password': 'bad-password',
                'csrfmiddlewaretoken': csrf_token,
            },
            HTTP_HOST='sh.elwsamstore.com',
            HTTP_REFERER='https://sh.elwsamstore.com/accounts/login/',
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
