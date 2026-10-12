from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Branch, User
from audit.models import AuditLog


class ProductionLoginRegressionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client(enforce_csrf_checks=True)
        self.main_branch, _ = Branch.objects.get_or_create(code='MAIN', defaults={'name': 'Main test branch'})

    def submit_login(self, user, password='login-test-only'):
        login_url = reverse('accounts:login')
        page = self.client.get(login_url)
        self.assertEqual(page.status_code, 200)
        return self.client.post(login_url, {
            'username': user.username,
            'password': password,
            'csrfmiddlewaretoken': page.cookies['csrftoken'].value,
        })

    def test_superuser_without_branch_can_log_in(self):
        user = User.objects.create_superuser(username='unscoped-admin', password='login-test-only')
        self.assertIsNone(user.branch_id)
        branch_count = Branch.objects.count()
        response = self.submit_login(user)
        self.assertRedirects(response, reverse('dashboard:index'), fetch_redirect_response=False)
        self.assertEqual(str(user.pk), self.client.session['_auth_user_id'])
        user.refresh_from_db()
        self.assertIsNotNone(user.last_login)
        self.assertIsNone(user.branch_id)
        self.assertEqual(Branch.objects.count(), branch_count)
        audit = AuditLog.all_objects.get(model_name='User', object_id=str(user.pk))
        self.assertEqual(audit.branch_id, self.main_branch.pk)
        self.assertIn('last_login', audit.changes_after)

    def test_manager_login_keeps_assigned_branch(self):
        branch = Branch.objects.create(name='Login branch', code='LOGIN')
        user = User.objects.create_user(username='login-manager', password='login-test-only', role='manager', branch=branch)
        response = self.submit_login(user)
        self.assertRedirects(response, reverse('dashboard:index'), fetch_redirect_response=False)
        user.refresh_from_db()
        self.assertEqual(user.branch_id, branch.pk)
        self.assertEqual(AuditLog.all_objects.get(model_name='User', object_id=str(user.pk)).branch_id, branch.pk)

    def test_superuser_password_hash_upgrade_does_not_break_login(self):
        user = User.objects.create_superuser(username='upgrade-admin', password='login-test-only')
        with override_settings(PASSWORD_HASHERS=[
            'django.contrib.auth.hashers.PBKDF2PasswordHasher',
            'django.contrib.auth.hashers.MD5PasswordHasher',
        ]):
            response = self.submit_login(user)
        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertTrue(user.password.startswith('pbkdf2_sha256$'))
        self.assertIsNone(user.branch_id)
        password_audit = AuditLog.all_objects.filter(model_name='User', object_id=str(user.pk)).order_by('pk').first()
        self.assertEqual(password_audit.changes_after['password'], '***REDACTED***')

    def test_inactive_branch_does_not_allow_manager_login(self):
        branch = Branch.objects.create(name='Inactive login branch', code='INACTIVE_LOGIN', is_active=False)
        user = User.objects.create_user(username='inactive-branch-manager', password='login-test-only', role='manager', branch=branch)
        response = self.submit_login(user)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_invalid_credentials_cannot_start_session(self):
        user = User.objects.create_superuser(username='invalid-login-admin', password='login-test-only')
        response = self.submit_login(user, password='incorrect-test-only')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertFalse(AuditLog.all_objects.filter(user=user).exists())

