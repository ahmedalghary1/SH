import re

from django.test import TestCase

from accounts.models import Branch, User


class OfflineReadinessTests(TestCase):
    def test_superuser_all_branches_uses_the_same_scope_as_the_server(self):
        branch = Branch.objects.create(code='PWA-READY', name='PWA readiness')
        user = User.objects.create_superuser(username='ready-root', branch=branch)
        self.client.force_login(user)
        response = self.client.get('/')
        html = response.content.decode()
        branch_value = re.search(r'data-pwa-branch-id="([^"]*)"', html).group(1)
        self.assertEqual(branch_value or 'all', 'all')
        scope = f'u{user.pk}-b{branch_value or "all"}-r{user.role}-s1'
        self.assertEqual(scope, response['X-PWA-Scope'])
        self.assertEqual(self.client.get('/api/sync/session/', HTTP_X_PWA_SCOPE=scope).status_code, 200)

    def test_offline_manifest_pages_are_readable_for_each_role(self):
        branch = Branch.objects.create(code='PWA-PAGES', name='Page readiness')
        for role in ['sales', 'warehouse', 'manager', 'superuser', 'superuser_sales']:
            user = User.objects.create_user(username=f'ready-{role}',
                role='manager' if role == 'superuser' else 'sales' if role == 'superuser_sales' else role,
                branch=branch, is_superuser=role.startswith('superuser'))
            self.client.force_login(user)
            response = self.client.get('/api/sync/bootstrap-browser/')
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            failed = []
            for path in payload['offline_pages']:
                page = self.client.get(path, HTTP_X_PWA_SCOPE=payload['scope'])
                if page.status_code != 200 or page.get('X-PWA-Cacheable') != '1':
                    failed.append((path, page.status_code, page.get('Location')))
            self.assertEqual(failed, [])

    def test_selected_superuser_branch_matches_html_header_and_session(self):
        assigned = Branch.objects.create(code='PWA-ASSIGNED', name='Assigned branch')
        selected = Branch.objects.create(code='PWA-SELECTED', name='Selected branch')
        user = User.objects.create_superuser(username='selected-root', branch=assigned, role='manager')
        self.client.force_login(user)
        session = self.client.session
        session['active_branch_id'] = selected.pk
        session.save()
        response = self.client.get('/')
        scope = response['X-PWA-Scope']
        self.assertContains(response, f'data-pwa-scope="{scope}"')
        self.assertContains(response, f'data-pwa-branch-id="{selected.pk}"')
        self.assertEqual(scope, f'u{user.pk}-b{selected.pk}-rmanager-s1')
        self.assertEqual(self.client.get('/api/sync/session/', HTTP_X_PWA_SCOPE=scope).json()['scope'], scope)
