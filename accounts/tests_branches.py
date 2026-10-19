from django.core.exceptions import ValidationError
from django.test import TestCase

from config.branching import reset_current_branch, set_current_branch
from customers.models import Customer
from inventory.models import Stock, Warehouse
from invoices.models import Invoice
from orders.models import Order
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


class TwoBranchWorkflowTests(TestCase):
    def setUp(self):
        self.branch_a = Branch.objects.create(name='معرض أ', code='SHOW-A')
        self.branch_b = Branch.objects.create(name='معرض ب', code='SHOW-B')
        self.user = User.objects.create_superuser(username='branch-owner', password='pass')
        self.products = {}
        self.invoices = {}
        for branch in (self.branch_a, self.branch_b):
            self.products[branch.pk] = Product.objects.create(
                branch=branch, name=f'منتج {branch.code}', sku='SAME-SKU',
            )
            customer = Customer.objects.create(
                branch=branch, name=f'عميل {branch.code}',
                customer_type=Customer.TYPE_B2C, created_by=self.user,
            )
            order = Order.objects.create(
                branch=branch, order_number='SAME-ORDER', order_type=Order.TYPE_B2C,
                customer=customer, created_by=self.user,
            )
            self.invoices[branch.pk] = Invoice.objects.create(
                branch=branch, order=order, invoice_number='SAME-INVOICE',
            )
        self.client.force_login(self.user)

    def select_branch(self, branch):
        response = self.client.post('/accounts/branches/select/', {'branch': branch.pk, 'next': '/'})
        self.assertEqual(response.status_code, 302)

    def test_switching_scopes_products_invoices_and_direct_links(self):
        for active, other in ((self.branch_a, self.branch_b), (self.branch_b, self.branch_a)):
            with self.subTest(active=active.code):
                self.select_branch(active)
                product_response = self.client.get('/products/')
                self.assertEqual(product_response.status_code, 200)
                self.assertEqual(
                    [item.pk for item in product_response.context['products']],
                    [self.products[active.pk].pk],
                )
                invoice_response = self.client.get('/invoices/')
                self.assertEqual(invoice_response.status_code, 200)
                self.assertEqual(
                    [item.pk for item in invoice_response.context['invoices']],
                    [self.invoices[active.pk].pk],
                )
                self.assertEqual(self.client.get(f'/products/{self.products[other.pk].pk}/').status_code, 404)
                self.assertEqual(self.client.get(f'/products/{self.products[other.pk].pk}/update/').status_code, 404)
                self.assertEqual(self.client.get(f'/invoices/{self.invoices[other.pk].pk}/').status_code, 404)
                self.assertEqual(self.client.get(f'/invoices/{self.invoices[other.pk].pk}/print/').status_code, 404)
                self.assertEqual(self.client.post(f'/invoices/{self.invoices[other.pk].pk}/print/mark/').status_code, 404)
                self.assertEqual(self.client.post(f'/invoices/{self.invoices[other.pk].pk}/payments/add/').status_code, 404)
                self.assertEqual(self.client.post(
                    f'/invoices/generate/{self.invoices[other.pk].order_id}/',
                ).status_code, 404)
                export = self.client.get('/invoices/export/excel/')
                self.assertEqual(export.status_code, 200)
                self.assertIn(b'SAME-INVOICE', export.content)
                self.assertEqual(export.content.count(b'SAME-INVOICE'), 1)

    def test_created_product_belongs_to_selected_branch(self):
        self.select_branch(self.branch_b)
        response = self.client.post('/products/create/', {
            'name': 'New branch product', 'sku': 'NEW-B',
            'new_category_name': 'Branch category',
            'new_color_name': 'Branch color', 'new_size_name': 'Branch size',
            'cost_price': '10', 'retail_price': '20', 'wholesale_price': '15',
        })
        self.assertEqual(response.status_code, 302)
        product = Product.all_objects.get(sku='NEW-B')
        self.assertEqual(product.branch_id, self.branch_b.pk)
        self.assertEqual(product.category.branch_id, self.branch_b.pk)
        self.assertEqual(product.variants.get().branch_id, self.branch_b.pk)
        self.select_branch(self.branch_a)
        self.assertEqual(self.client.get(f'/products/{product.pk}/').status_code, 404)
