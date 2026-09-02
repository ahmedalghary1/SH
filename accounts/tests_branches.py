from django.core.exceptions import ValidationError
from django.test import TestCase

from config.branching import reset_current_branch, set_current_branch
from inventory.models import Stock, Warehouse
from products.models import Product, ProductVariant
from sync_api.auth import make_token

from .models import Branch, User


class BranchIsolationTests(TestCase):
    def setUp(self):
        self.branch_a = Branch.objects.create(name='معرض أ', code='A')
        self.branch_b = Branch.objects.create(name='معرض ب', code='B')
        self.user_a = User.objects.create_user(username='branch-a', password='pass', branch=self.branch_a, role=User.ROLE_MANAGER)
        self.product_a = Product.objects.create(branch=self.branch_a, name='منتج أ', sku='SAME')
        self.product_b = Product.objects.create(branch=self.branch_b, name='منتج ب', sku='SAME')

    def test_manager_scopes_records_to_current_branch(self):
        token = set_current_branch(self.branch_a.pk)
        try:
            self.assertEqual(list(Product.objects.values_list('pk', flat=True)), [self.product_a.pk])
            self.assertEqual(Product.all_objects.filter(sku='SAME').count(), 2)
        finally:
            reset_current_branch(token)

    def test_same_sku_is_allowed_in_different_branches(self):
        self.assertEqual(Product.all_objects.filter(sku='SAME').count(), 2)

    def test_cross_branch_stock_is_rejected(self):
        warehouse = Warehouse.objects.create(branch=self.branch_a, name='مخزن أ', warehouse_type=Warehouse.TYPE_MAIN)
        variant = ProductVariant.objects.create(branch=self.branch_b, product=self.product_b, variant_sku='V-1')
        with self.assertRaises(ValidationError):
            Stock.objects.create(branch=self.branch_a, warehouse=warehouse, variant=variant, quantity=1)

    def test_http_request_hides_other_branch_products(self):
        self.client.force_login(self.user_a)
        response = self.client.get('/products/')
        self.assertEqual(response.status_code, 200)
        products = list(response.context['products'])
        self.assertEqual([product.pk for product in products], [self.product_a.pk])

    def test_token_sync_is_scoped_to_the_users_branch(self):
        token = make_token(self.user_a, 'test-device')
        response = self.client.get('/api/sync/bootstrap/', HTTP_AUTHORIZATION=f'Bearer {token}')
        self.assertEqual(response.status_code, 200)
        product_ids = [row['id'] for row in response.json()['products']]
        self.assertEqual(product_ids, [self.product_a.pk])


class SuperuserBranchSelectionTests(TestCase):
    def test_superuser_can_switch_between_all_and_one_branch(self):
        branch = Branch.objects.create(name='فرع محدد', code='SELECTED')
        superuser = User.objects.create_superuser(username='root-branch-test', password='pass')
        self.client.force_login(superuser)
        response = self.client.post('/accounts/branches/select/', {'branch': branch.pk, 'next': '/'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session['active_branch_id'], branch.pk)
        response = self.client.post('/accounts/branches/select/', {'branch': '', 'next': '/'})
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('active_branch_id', self.client.session)
