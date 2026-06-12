from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from config.pdf_utils import shape_arabic

from .models import Category, Color, Product, ProductVariant, Size


class BulkPriceUpdateViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='manager', password='pass', role=User.ROLE_MANAGER)
        self.client.force_login(self.user)
        self.category = Category.objects.create(name='عبايات')
        self.color = Color.objects.create(name='أسود')
        self.size = Size.objects.create(name='M', sort_order=1)
        self.product = Product.objects.create(name='عباية كلاسيك', sku='AB-001', category=self.category)
        self.variant = ProductVariant.objects.create(
            product=self.product,
            color=self.color,
            size=self.size,
            variant_sku='AB-001-BLK-M',
            cost_price=Decimal('120.00'),
            sale_price=Decimal('250.00'),
        )

    def test_price_update_page_lists_products_with_price_inputs(self):
        response = self.client.get(reverse('products:bulk_price_update'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.product.name)
        self.assertContains(response, 'السعر القديم')
        self.assertContains(response, f'name="price_{self.variant.pk}"')
        self.assertNotContains(response, 'name="cost_price"')

    def test_products_page_has_price_update_action(self):
        response = self.client.get(reverse('products:list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('products:bulk_price_update'))
        self.assertContains(response, 'تحديث الأسعار')
        self.assertContains(response, 'تصدير Excel')
        self.assertContains(response, 'تحميل PDF')

    def test_products_can_be_exported(self):
        excel_response = self.client.get(f'{reverse("products:list")}?export=excel')
        pdf_response = self.client.get(f'{reverse("products:list")}?export=pdf')

        self.assertEqual(excel_response.status_code, 200)
        self.assertEqual(excel_response['Content-Type'], 'text/csv; charset=utf-8-sig')
        self.assertContains(excel_response, self.product.name)
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response['Content-Type'], 'application/pdf')

    def test_post_updates_sale_price_only(self):
        response = self.client.post(reverse('products:bulk_price_update'), {
            'variant_id': [str(self.variant.pk)],
            f'price_{self.variant.pk}': '310.50',
        })

        self.assertRedirects(response, reverse('products:bulk_price_update'))
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.sale_price, Decimal('310.50'))
        self.assertEqual(self.variant.cost_price, Decimal('120.00'))

    def test_invalid_price_keeps_existing_price(self):
        response = self.client.post(reverse('products:bulk_price_update'), {
            'variant_id': [str(self.variant.pk)],
            f'price_{self.variant.pk}': '-1',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'السعر لا يمكن أن يكون سالبا')
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.sale_price, Decimal('250.00'))

    def test_product_update_page_has_variant_price_input(self):
        response = self.client.get(reverse('products:update', args=[self.product.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'الألوان والمقاسات والأسعار')
        self.assertContains(response, f'name="variant_{self.variant.pk}_sale_price"')
        self.assertContains(response, 'value="250.00"')

    def test_product_update_changes_variant_sale_price(self):
        response = self.client.post(reverse('products:update', args=[self.product.pk]), {
            'name': self.product.name,
            'sku': self.product.sku,
            'category': str(self.category.pk),
            'material': self.product.material or '',
            'variant_id': [str(self.variant.pk)],
            f'variant_{self.variant.pk}_sale_price': '275.25',
        })

        self.assertRedirects(response, reverse('products:detail', args=[self.product.pk]))
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.sale_price, Decimal('275.25'))

    def test_variant_create_page_has_image_field(self):
        response = self.client.get(f'{reverse("products:variant_create")}?product={self.product.pk}')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="image"')
        self.assertContains(response, 'type="file"')

    def test_pdf_arabic_text_is_shaped(self):
        self.assertNotEqual(shape_arabic('تقرير المنتجات'), 'تقرير المنتجات')
