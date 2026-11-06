from decimal import Decimal
from unittest.mock import patch

from django.db import IntegrityError
from django.test import TestCase

from accounts.models import Branch, User
from config.branching import get_default_branch_id, reset_current_branch, set_current_branch
from finance.models import CashAccount
from sync_api.auth import make_token


class CashAccountBranchLookupTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.main_id = get_default_branch_id()
        cls.other = Branch.objects.create(code='CASH-OTHER', name='Other cash branch')
        for name in ('الخزنة الرئيسية', 'درج النقدية'):
            CashAccount.objects.create(branch_id=cls.main_id, name=name, balance=Decimal('10'))
            CashAccount.objects.create(branch=cls.other, name=name, balance=Decimal('20'))

    def test_unscoped_lookup_uses_default_branch_without_changing_balances(self):
        token = set_current_branch(None)
        try:
            for factory in (CashAccount.get_default, CashAccount.get_cash_drawer):
                account = factory()
                self.assertEqual(account.branch_id, self.main_id)
                self.assertEqual(account.balance, Decimal('10'))
                self.assertEqual(factory().pk, account.pk)
        finally:
            reset_current_branch(token)
        self.assertEqual(CashAccount.all_objects.count(), 4)
        self.assertEqual(list(CashAccount.all_objects.filter(branch=self.other).values_list('balance', flat=True)),
                         [Decimal('20'), Decimal('20')])

    def test_selected_branch_returns_its_own_accounts(self):
        token = set_current_branch(self.other.pk)
        try:
            for factory in (CashAccount.get_default, CashAccount.get_cash_drawer):
                self.assertEqual(factory().branch_id, self.other.pk)
                self.assertEqual(factory().balance, Decimal('20'))
        finally:
            reset_current_branch(token)

    def test_default_is_created_in_main_when_only_other_branch_has_one(self):
        CashAccount.all_objects.filter(branch_id=self.main_id, name='الخزنة الرئيسية').delete()
        token = set_current_branch(None)
        try:
            account = CashAccount.get_default()
            self.assertEqual(account.branch_id, self.main_id)
            self.assertEqual(account.balance, 0)
        finally:
            reset_current_branch(token)

    def test_unscoped_sales_cash_uses_assigned_users_branch(self):
        sales = User.objects.create_user(username='cash-scope-sales', role='sales', branch=self.other)
        token = set_current_branch(None)
        try:
            account = CashAccount.get_for_user(sales)
            self.assertEqual(account.branch_id, self.other.pk)
            self.assertEqual(CashAccount.get_for_user(sales).pk, account.pk)
        finally:
            reset_current_branch(token)

    def test_integrity_error_recovery_keeps_explicit_branch_filter(self):
        token = set_current_branch(None)
        try:
            with patch.object(CashAccount.objects, 'get_or_create', side_effect=IntegrityError):
                self.assertEqual(CashAccount.get_default().branch_id, self.main_id)
        finally:
            reset_current_branch(token)

    def test_browser_bootstrap_all_branches_handles_matching_account_names(self):
        user = User.objects.create_superuser(username='cash-bootstrap-root', password='pass')
        self.client.force_login(user)
        response = self.client.get('/api/sync/bootstrap-browser/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Decimal(response.json()['cash']['balance']), Decimal('10'))
        self.assertEqual(len(response.json()['cash_accounts']), 4)
        self.assertEqual(CashAccount.all_objects.count(), 4)

    def test_browser_bootstrap_selected_branch_uses_selected_cash(self):
        user = User.objects.create_superuser(username='cash-selected-root', password='pass')
        self.client.force_login(user)
        session = self.client.session
        session['active_branch_id'] = self.other.pk
        session.save()
        response = self.client.get('/api/sync/bootstrap-browser/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Decimal(response.json()['cash']['balance']), Decimal('20'))
        self.assertEqual(len(response.json()['cash_accounts']), 2)

    def test_token_bootstrap_all_branches_handles_matching_account_names(self):
        user = User.objects.create_superuser(username='cash-token-root', password='pass')
        response = self.client.get('/api/sync/bootstrap/', HTTP_AUTHORIZATION=f'Bearer {make_token(user)}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['cash_accounts']), 4)
