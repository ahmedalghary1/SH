from decimal import Decimal
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from openpyxl import Workbook

from accounts.models import User
from config.pdf_utils import shape_arabic
from inventory.models import Stock, StockBatch, StockMovement, Warehouse

from .models import Category, Color, Product, ProductVariant, Size


def product_import_file(rows, headers=None, *, right_to_left=True, filename='products.xlsx'):
    workbook = Workbook()
    sheet = workbook.active
    sheet.sheet_view.rightToLeft = right_to_left
    sheet.append(headers or ['م', 'الكود', 'اسم الصنف', 'الوكيل', 'الجملة', 'القطاعي', 'السنه'])
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return SimpleUploadedFile(
        filename,
        output.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )


class ProductImportViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='import-manager', password='pass', role=User.ROLE_MANAGER)
        self.client.force_login(self.user)

    def test_products_page_has_excel_import_action(self):
        response = self.client.get(reverse('products:list'))

        self.assertContains(response, reverse('products:import'))
        self.assertContains(response, 'استيراد من Excel')

    def test_import_creates_product_and_default_variant_from_rtl_sheet(self):
        # Excel number formatting is commonly used to retain leading zeros in codes.
        workbook = Workbook()
        sheet = workbook.active
        sheet.sheet_view.rightToLeft = True
        sheet.append(['م', 'الكود', 'اسم الصنف', 'الوكيل', 'الجملة', 'القطاعي', 'السنه'])
        sheet.append([1, 7, 'صنف تجريبي', 'وكيل القاهرة', 100, 125.5, 2026])
        sheet['B2'].number_format = '000'
        output = BytesIO()
        workbook.save(output)
        workbook.close()
        product_file = SimpleUploadedFile('products.xlsx', output.getvalue())

        response = self.client.post(reverse('products:import'), {'product_file': product_file})

        self.assertRedirects(response, reverse('products:list'))
        product = Product.objects.get(sku='007')
        self.assertEqual(product.name, 'صنف تجريبي')
        self.assertEqual(product.agent, 'وكيل القاهرة')
        self.assertEqual(product.season, '2026')
        self.assertEqual(product.wholesale_price, Decimal('100.00'))
        self.assertEqual(product.retail_price, Decimal('125.50'))
        variant = product.variants.get()
        self.assertIsNone(variant.color)
        self.assertIsNone(variant.size)
        self.assertEqual(variant.sale_price, Decimal('125.50'))
        self.assertEqual(variant.retail_price, Decimal('125.50'))
        self.assertEqual(variant.wholesale_price, Decimal('100.00'))

    def test_invalid_row_is_skipped_while_valid_rows_are_imported(self):
        product_file = product_import_file([
            [1, 'OK-1', 'صنف صحيح', 'وكيل', '50', '60', '2026'],
            [2, 'BAD-1', '', 'وكيل', 'not-a-price', '70', '2026'],
        ])

        response = self.client.post(reverse('products:import'), {'product_file': product_file})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Product.objects.filter(sku='OK-1').exists())
        self.assertFalse(Product.objects.filter(sku='BAD-1').exists())
        self.assertContains(response, 'تم استيراد <strong>1</strong> منتج', html=True)
        self.assertContains(response, 'الصف 3')

    def test_existing_sku_is_skipped_without_overwriting_product(self):
        existing = Product.objects.create(name='الاسم القديم', sku='DUP-1')
        product_file = product_import_file([
            [1, 'DUP-1', 'الاسم الجديد', 'وكيل', 50, 60, 2026],
        ])

        response = self.client.post(reverse('products:import'), {'product_file': product_file})

        self.assertEqual(response.status_code, 200)
        existing.refresh_from_db()
        self.assertEqual(existing.name, 'الاسم القديم')
        self.assertContains(response, 'الكود موجود بالفعل في النظام')

    def test_wrong_headers_are_rejected(self):
        product_file = product_import_file(
            [[1, 'P-1', 'منتج']],
            headers=['م', 'الكود', 'اسم الصنف'],
        )

        response = self.client.post(reverse('products:import'), {'product_file': product_file})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'عناوين الصف الأول غير صحيحة')
        self.assertFalse(Product.objects.exists())

    def test_non_manager_cannot_open_import_page(self):
        warehouse_user = User.objects.create_user(username='warehouse-import', password='pass', role=User.ROLE_WAREHOUSE)
        self.client.force_login(warehouse_user)

        response = self.client.get(reverse('products:import'))

        self.assertEqual(response.status_code, 403)


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


class ProductCreateViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='manager2', password='pass', role=User.ROLE_MANAGER)
        self.client.force_login(self.user)
        self.category = Category.objects.create(name='Category')
        self.color = Color.objects.create(name='Black')
        self.size = Size.objects.create(name='L', sort_order=1)
        self.warehouse = Warehouse.objects.create(name='Main Warehouse', warehouse_type=Warehouse.TYPE_MAIN)

    def test_opening_balance_creates_opening_stock_movement(self):
        response = self.client.post(reverse('products:create'), {
            'name': 'Opening Product',
            'sku': 'OPEN-001',
            'category': self.category.pk,
            'material': '',
            'pieces_per_dozen': '12',
            'color': self.color.pk,
            'new_color_name': '',
            'size': self.size.pk,
            'new_size_name': '',
            'cost_price': '25.00',
            'retail_price': '50.00',
            'wholesale_price': '40.00',
            'warehouse': self.warehouse.pk,
            'new_warehouse_name': '',
            'quantity': '7',
        })

        product = Product.objects.get(sku='OPEN-001')
        self.assertRedirects(response, reverse('products:detail', args=[product.pk]))
        variant = product.variants.get()
        self.assertEqual(Stock.objects.get(warehouse=self.warehouse, variant=variant).quantity, 7)

        movement = StockMovement.objects.get(variant=variant)
        self.assertEqual(movement.movement_type, StockMovement.TYPE_OPENING_BALANCE)
        self.assertEqual(movement.quantity, 7)

        batch = StockBatch.objects.get(variant=variant, warehouse=self.warehouse)
        self.assertEqual(batch.source, 'opening_balance')
        self.assertEqual(batch.received_quantity, 7)

    def test_create_multiple_color_size_combinations_with_independent_quantities(self):
        second_color = Color.objects.create(name='White')
        second_size = Size.objects.create(name='XL', sort_order=2)

        response = self.client.post(reverse('products:create'), {
            'bulk_variants': '1',
            'name': 'Bulk Variant Product',
            'sku': 'BULK-001',
            'category': self.category.pk,
            'material': '',
            'pieces_per_dozen': '12',
            'colors': [str(self.color.pk), str(second_color.pk)],
            'sizes': [str(self.size.pk), str(second_size.pk)],
            'cost_price': '25.00',
            'retail_price': '50.00',
            'wholesale_price': '40.00',
            'warehouse': self.warehouse.pk,
            'quantity_{0}_{1}'.format(self.color.pk, self.size.pk): '2',
            'quantity_{0}_{1}'.format(self.color.pk, second_size.pk): '3',
            'quantity_{0}_{1}'.format(second_color.pk, self.size.pk): '4',
            'quantity_{0}_{1}'.format(second_color.pk, second_size.pk): '5',
        })

        product = Product.objects.get(sku='BULK-001')
        self.assertRedirects(response, reverse('products:detail', args=[product.pk]))
        self.assertEqual(product.variants.count(), 4)
        quantities = {
            (stock.variant.color_id, stock.variant.size_id): stock.quantity
            for stock in Stock.objects.filter(variant__product=product).select_related('variant')
        }
        self.assertEqual(quantities, {
            (self.color.pk, self.size.pk): 2,
            (self.color.pk, second_size.pk): 3,
            (second_color.pk, self.size.pk): 4,
            (second_color.pk, second_size.pk): 5,
        })
        self.assertEqual(StockMovement.objects.filter(variant__product=product).count(), 4)

    def test_bulk_quantities_require_a_warehouse(self):
        response = self.client.post(reverse('products:create'), {
            'bulk_variants': '1',
            'name': 'No Warehouse Product',
            'sku': 'NO-WAREHOUSE',
            'category': self.category.pk,
            'pieces_per_dozen': '12',
            'colors': [str(self.color.pk)],
            'sizes': [str(self.size.pk)],
            'cost_price': '25.00',
            'retail_price': '50.00',
            'wholesale_price': '40.00',
            'quantity_{0}_{1}'.format(self.color.pk, self.size.pk): '2',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'اختر المخزن لإضافة الكميات الافتتاحية')
        self.assertFalse(Product.objects.filter(sku='NO-WAREHOUSE').exists())

    def test_create_page_shows_bulk_variant_builder(self):
        response = self.client.get(reverse('products:create'))

        self.assertContains(response, 'name="bulk_variants"')
        self.assertContains(response, 'name="colors"')
        self.assertContains(response, 'name="sizes"')
        self.assertContains(response, 'id="variant-quantity-rows"')

    def test_bulk_create_reports_product_and_quantity_errors_together(self):
        response = self.client.post(reverse('products:create'), {
            'bulk_variants': '1',
            'name': '',
            'sku': '',
            'category': self.category.pk,
            'pieces_per_dozen': '12',
            'colors': [str(self.color.pk)],
            'sizes': [str(self.size.pk)],
            'cost_price': '25.00',
            'retail_price': '50.00',
            'wholesale_price': '40.00',
            'quantity_{0}_{1}'.format(self.color.pk, self.size.pk): '-1',
        })

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['product_form'].errors['name'])
        self.assertTrue(response.context['product_form'].errors['sku'])
        self.assertContains(response, 'غير صحيحة')

    def test_create_reuses_first_category_when_legacy_duplicates_exist(self):
        Category.objects.create(name='Duplicate Category')
        Category.objects.create(name='Duplicate Category')

        response = self.client.post(reverse('products:create'), {
            'bulk_variants': '1',
            'name': 'Duplicate Category Product',
            'sku': 'DUP-CATEGORY-001',
            'category': '',
            'new_category_name': 'Duplicate Category',
            'pieces_per_dozen': '12',
            'colors': [str(self.color.pk)],
            'sizes': [str(self.size.pk)],
            'cost_price': '25.00',
            'retail_price': '50.00',
            'wholesale_price': '40.00',
        })

        product = Product.objects.get(sku='DUP-CATEGORY-001')
        self.assertRedirects(response, reverse('products:detail', args=[product.pk]))
        self.assertEqual(product.category.name, 'Duplicate Category')

    def test_create_reuses_first_warehouse_when_legacy_duplicates_exist(self):
        Warehouse.objects.create(name=self.warehouse.name, warehouse_type=Warehouse.TYPE_MAIN)

        response = self.client.post(reverse('products:create'), {
            'bulk_variants': '1',
            'name': 'Duplicate Warehouse Product',
            'sku': 'DUP-WAREHOUSE-001',
            'category': self.category.pk,
            'pieces_per_dozen': '12',
            'colors': [str(self.color.pk)],
            'sizes': [str(self.size.pk)],
            'cost_price': '25.00',
            'retail_price': '50.00',
            'wholesale_price': '40.00',
            'new_warehouse_name': self.warehouse.name,
            'quantity_{0}_{1}'.format(self.color.pk, self.size.pk): '3',
        })

        product = Product.objects.get(sku='DUP-WAREHOUSE-001')
        self.assertRedirects(response, reverse('products:detail', args=[product.pk]))
        stock = Stock.objects.get(variant__product=product)
        self.assertEqual(stock.warehouse, self.warehouse)
        self.assertEqual(stock.quantity, 3)

    def test_bulk_create_rejects_quantity_larger_than_database_integer(self):
        response = self.client.post(reverse('products:create'), {
            'bulk_variants': '1',
            'name': 'Oversized Stock Product',
            'sku': 'OVERSIZED-STOCK-001',
            'category': self.category.pk,
            'pieces_per_dozen': '12',
            'colors': [str(self.color.pk)],
            'sizes': [str(self.size.pk)],
            'cost_price': '25.00',
            'retail_price': '50.00',
            'wholesale_price': '40.00',
            'warehouse': self.warehouse.pk,
            'quantity_{0}_{1}'.format(self.color.pk, self.size.pk): '2147483648',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'غير صحيحة')
        self.assertFalse(Product.objects.filter(sku='OVERSIZED-STOCK-001').exists())
