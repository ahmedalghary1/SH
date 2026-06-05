from decimal import Decimal
from random import Random

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from customers.models import Customer
from inventory.models import Stock, StockMovement, Warehouse
from invoices.models import Invoice
from orders.models import Order, OrderItem
from products.models import Category, Color, Product, ProductVariant, Size
from settings_app.models import CompanySettings


class Command(BaseCommand):
    help = 'Seed the database with realistic demo data for the clothing ERP.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset-demo',
            action='store_true',
            help='Delete seeded demo records before recreating them.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options['reset_demo']:
            self._reset_demo_data()

        rng = Random(20260603)
        users = self._seed_users()
        settings = CompanySettings.load()
        settings.company_name = 'شركة الشروق للملابس الجاهزة'
        settings.phone = '0100 445 7788'
        settings.email = 'sales@shorouk-fashion.test'
        settings.address = '18 شارع التحرير، الدقي، الجيزة'
        settings.tax_number = 'EG-563-884-219'
        settings.invoice_notes = 'شكرا لتعاملكم معنا. الاستبدال خلال 14 يوما بشرط سلامة المنتج.'
        settings.save()

        categories = self._seed_categories()
        colors = self._seed_colors()
        sizes = self._seed_sizes()
        variants = self._seed_products(categories, colors, sizes)
        warehouses = self._seed_warehouses(users)
        self._seed_stock(variants, warehouses, users, rng)
        customers = self._seed_customers(users)
        self._seed_orders(customers, variants, warehouses, users, rng)

        self.stdout.write(self.style.SUCCESS('Demo data seeded successfully.'))

    def _reset_demo_data(self):
        Invoice.objects.filter(invoice_number__startswith='INV-DEMO-').delete()
        Order.objects.filter(order_number__startswith='ORD-DEMO-').delete()
        StockMovement.objects.filter(note__startswith='Demo').delete()
        Stock.objects.filter(variant__variant_sku__startswith='DEMO-').delete()
        ProductVariant.objects.filter(variant_sku__startswith='DEMO-').delete()
        Product.objects.filter(sku__startswith='DEMO-').delete()
        Customer.objects.filter(phone__startswith='0109').delete()
        Warehouse.objects.filter(name__in=[
            'المخزن الرئيسي - العبور',
            'فرع مدينة نصر',
            'فرع المعادي',
            'عهدة أحمد سمير',
            'عهدة سارة محمود',
        ]).delete()

    def _seed_users(self):
        manager, _ = User.objects.update_or_create(
            username='admin',
            defaults={
                'role': User.ROLE_MANAGER,
                'is_staff': True,
                'is_superuser': True,
                'first_name': 'مصطفى',
                'last_name': 'حسن',
                'phone': '01001234567',
                'email': 'admin@shorouk-fashion.test',
            },
        )
        if not manager.has_usable_password():
            manager.set_password('admin12345')
            manager.save(update_fields=['password'])

        warehouse_user, _ = User.objects.update_or_create(
            username='warehouse',
            defaults={
                'role': User.ROLE_WAREHOUSE,
                'first_name': 'كريم',
                'last_name': 'فؤاد',
                'phone': '01005554444',
                'email': 'warehouse@shorouk-fashion.test',
                'is_active': True,
            },
        )
        warehouse_user.set_password('warehouse123')
        warehouse_user.save(update_fields=['password'])

        sales_ahmed, _ = User.objects.update_or_create(
            username='ahmed.sales',
            defaults={
                'role': User.ROLE_SALES,
                'first_name': 'أحمد',
                'last_name': 'سمير',
                'phone': '01006667771',
                'email': 'ahmed@shorouk-fashion.test',
                'is_active': True,
            },
        )
        sales_ahmed.set_password('sales123')
        sales_ahmed.save(update_fields=['password'])

        sales_sara, _ = User.objects.update_or_create(
            username='sara.sales',
            defaults={
                'role': User.ROLE_SALES,
                'first_name': 'سارة',
                'last_name': 'محمود',
                'phone': '01006667772',
                'email': 'sara@shorouk-fashion.test',
                'is_active': True,
            },
        )
        sales_sara.set_password('sales123')
        sales_sara.save(update_fields=['password'])

        return {
            'manager': manager,
            'warehouse': warehouse_user,
            'sales_ahmed': sales_ahmed,
            'sales_sara': sales_sara,
        }

    def _seed_categories(self):
        names = ['قمصان', 'تيشيرتات', 'بناطيل', 'فساتين', 'جاكيتات', 'إكسسوارات']
        return {name: Category.objects.update_or_create(name=name, defaults={'is_active': True})[0] for name in names}

    def _seed_colors(self):
        data = [
            ('أبيض', '#FFFFFF'),
            ('أسود', '#111827'),
            ('كحلي', '#0B2E50'),
            ('بيج', '#D6B88D'),
            ('زيتوني', '#66785F'),
            ('أحمر', '#C2413A'),
            ('لبني', '#7DD3FC'),
        ]
        return {
            name: Color.objects.update_or_create(name=name, defaults={'hex_code': hex_code})[0]
            for name, hex_code in data
        }

    def _seed_sizes(self):
        names = [('S', 1), ('M', 2), ('L', 3), ('XL', 4), ('XXL', 5), ('36', 6), ('38', 7), ('40', 8), ('42', 9)]
        return {
            name: Size.objects.update_or_create(name=name, defaults={'sort_order': order})[0]
            for name, order in names
        }

    def _seed_products(self, categories, colors, sizes):
        product_data = [
            ('DEMO-SH-001', 'قميص أوكسفورد رجالي', 'قمصان', Decimal('540'), Decimal('395'), ['أبيض', 'كحلي', 'لبني'], ['M', 'L', 'XL']),
            ('DEMO-TS-002', 'تيشيرت قطن مطبوع', 'تيشيرتات', Decimal('320'), Decimal('230'), ['أسود', 'أبيض', 'زيتوني'], ['S', 'M', 'L', 'XL']),
            ('DEMO-TR-003', 'بنطلون تشينو Slim Fit', 'بناطيل', Decimal('690'), Decimal('510'), ['بيج', 'كحلي', 'أسود'], ['38', '40', '42']),
            ('DEMO-DR-004', 'فستان صيفي كتان', 'فساتين', Decimal('880'), Decimal('660'), ['أحمر', 'بيج', 'زيتوني'], ['S', 'M', 'L']),
            ('DEMO-JK-005', 'جاكيت جينز خفيف', 'جاكيتات', Decimal('1250'), Decimal('930'), ['كحلي', 'أسود'], ['M', 'L', 'XL']),
            ('DEMO-AC-006', 'حزام جلد كلاسيك', 'إكسسوارات', Decimal('280'), Decimal('190'), ['أسود', 'بيج'], ['M', 'L']),
        ]

        variants = []
        for sku, name, category_name, retail, wholesale, product_colors, product_sizes in product_data:
            product, _ = Product.objects.update_or_create(
                sku=sku,
                defaults={
                    'name': name,
                    'category': categories[category_name],
                    'description': f'{name} مناسب للاستخدام اليومي والموسمي بجودة تشطيب عالية.',
                    'material': 'قطن مخلوط' if category_name != 'إكسسوارات' else 'جلد صناعي فاخر',
                    'season': 'صيف / ربيع' if category_name in {'تيشيرتات', 'فساتين'} else 'كل المواسم',
                    'retail_price': retail,
                    'wholesale_price': wholesale,
                    'is_active': True,
                },
            )
            for color_name in product_colors:
                for size_name in product_sizes:
                    variant_sku = f'{sku}-{color_name[:2]}-{size_name}'.replace(' ', '')
                    variant, _ = ProductVariant.objects.update_or_create(
                        variant_sku=variant_sku,
                        defaults={
                            'product': product,
                            'color': colors[color_name],
                            'size': sizes[size_name],
                            'barcode': f'622{abs(hash(variant_sku)) % 1000000000:09d}',
                            'cost_price': wholesale,
                            'sale_price': retail,
                            'is_active': True,
                        },
                    )
                    variants.append(variant)
        return variants

    def _seed_warehouses(self, users):
        data = [
            ('المخزن الرئيسي - العبور', Warehouse.TYPE_MAIN, None, 'المنطقة الصناعية، العبور'),
            ('فرع مدينة نصر', Warehouse.TYPE_STORE, None, 'شارع عباس العقاد، مدينة نصر'),
            ('فرع المعادي', Warehouse.TYPE_STORE, None, 'شارع النصر، المعادي'),
            ('عهدة أحمد سمير', Warehouse.TYPE_REPRESENTATIVE, users['sales_ahmed'], 'منطقة شرق القاهرة'),
            ('عهدة سارة محمود', Warehouse.TYPE_REPRESENTATIVE, users['sales_sara'], 'منطقة الجيزة'),
        ]
        warehouses = {}
        for name, warehouse_type, assigned_user, address in data:
            warehouses[name], _ = Warehouse.objects.update_or_create(
                name=name,
                defaults={
                    'warehouse_type': warehouse_type,
                    'assigned_user': assigned_user,
                    'address': address,
                    'is_active': True,
                },
            )
        return warehouses

    def _seed_stock(self, variants, warehouses, users, rng):
        stock_ranges = {
            'المخزن الرئيسي - العبور': (35, 140),
            'فرع مدينة نصر': (8, 45),
            'فرع المعادي': (6, 38),
            'عهدة أحمد سمير': (2, 18),
            'عهدة سارة محمود': (2, 16),
        }
        for warehouse_name, warehouse in warehouses.items():
            low_counter = 0
            for index, variant in enumerate(variants):
                low_item = index % 17 == 0 and low_counter < 4
                min_qty = 8 if warehouse.warehouse_type == Warehouse.TYPE_MAIN else 3
                if low_item:
                    quantity = rng.randint(0, min_qty)
                    low_counter += 1
                else:
                    start, end = stock_ranges[warehouse_name]
                    quantity = rng.randint(start, end)
                Stock.objects.update_or_create(
                    warehouse=warehouse,
                    variant=variant,
                    defaults={'quantity': quantity, 'min_quantity': min_qty},
                )

            StockMovement.objects.get_or_create(
                movement_type=StockMovement.TYPE_IN,
                variant=variants[0],
                to_warehouse=warehouse,
                quantity=25,
                note=f'Demo opening balance - {warehouse.name}',
                created_by=users['warehouse'],
            )

    def _seed_customers(self, users):
        data = [
            ('محمد عبد الرحمن', Customer.TYPE_B2C, '01090010001', '', 'مدينة نصر، القاهرة'),
            ('منة خالد', Customer.TYPE_B2C, '01090010002', '', 'المعادي، القاهرة'),
            ('أحمد الشناوي', Customer.TYPE_B2C, '01090010003', '', 'الهرم، الجيزة'),
            ('نوران ياسر', Customer.TYPE_B2C, '01090010004', '', 'التجمع الخامس، القاهرة'),
            ('كريم عادل', Customer.TYPE_B2C, '01090010005', '', 'شبرا، القاهرة'),
            ('هالة مصطفى', Customer.TYPE_B2C, '01090010006', '', 'سيدي جابر، الإسكندرية'),
            ('مؤسسة الندى للتجارة', Customer.TYPE_B2B, '01090010007', 'الندى للتجارة', 'طنطا، الغربية'),
            ('شركة بيسك فاشون', Customer.TYPE_B2B, '01090010008', 'Basic Fashion', 'شارع سوريا، المهندسين'),
            ('بوتيك روز', Customer.TYPE_B2B, '01090010009', 'Rose Boutique', 'المنصورة، الدقهلية'),
            ('هاي ستايل ستور', Customer.TYPE_B2B, '01090010010', 'High Style Store', 'بورسعيد'),
            ('محمود فوزي', Customer.TYPE_B2C, '01090010011', '', 'الزقازيق، الشرقية'),
            ('سلمى أشرف', Customer.TYPE_B2C, '01090010012', '', '6 أكتوبر، الجيزة'),
        ]
        customers = []
        for index, (name, customer_type, phone, company, address) in enumerate(data, start=1):
            customer, _ = Customer.objects.update_or_create(
                phone=phone,
                defaults={
                    'name': name,
                    'customer_type': customer_type,
                    'whatsapp': phone,
                    'email': f'customer{index}@example.test',
                    'company_name': company or None,
                    'tax_number': f'TAX-DEMO-{index:03d}' if customer_type == Customer.TYPE_B2B else None,
                    'address': address,
                    'notes': 'عميل demo للاختبار وتجربة الشاشات.',
                    'is_active': True,
                    'created_by': users['manager'],
                },
            )
            customers.append(customer)
        return customers

    def _seed_orders(self, customers, variants, warehouses, users, rng):
        usable_warehouses = [
            warehouses['فرع مدينة نصر'],
            warehouses['فرع المعادي'],
            warehouses['عهدة أحمد سمير'],
            warehouses['عهدة سارة محمود'],
        ]
        statuses = [
            Order.STATUS_COMPLETED,
            Order.STATUS_COMPLETED,
            Order.STATUS_CONFIRMED,
            Order.STATUS_PREPARING,
            Order.STATUS_READY,
            Order.STATUS_DRAFT,
            Order.STATUS_RETURNED,
        ]
        methods = [Order.METHOD_CASH, Order.METHOD_COD, Order.METHOD_BANK, Order.METHOD_WALLET]
        today = timezone.localdate()

        for index in range(1, 25):
            customer = customers[(index - 1) % len(customers)]
            warehouse = usable_warehouses[index % len(usable_warehouses)]
            status = statuses[index % len(statuses)]
            order_type = Order.TYPE_B2B if customer.customer_type == Customer.TYPE_B2B else Order.TYPE_B2C
            order_number = f'ORD-DEMO-{today.strftime("%Y%m")}-{index:04d}'
            created_by = users['sales_ahmed'] if index % 2 else users['sales_sara']
            payment_method = methods[index % len(methods)]
            order, _ = Order.objects.update_or_create(
                order_number=order_number,
                defaults={
                    'order_type': order_type,
                    'customer': customer,
                    'warehouse': warehouse,
                    'status': status,
                    'payment_method': payment_method,
                    'wallet_from_number': '01090018888' if payment_method == Order.METHOD_WALLET else '',
                    'wallet_to_number': '01005559999' if payment_method == Order.METHOD_WALLET else '',
                    'discount': Decimal(str((index % 4) * 25)),
                    'notes': 'طلب demo ببيانات قريبة من التشغيل الحقيقي.',
                    'created_by': created_by,
                },
            )
            order.items.all().delete()

            item_count = 1 + (index % 3)
            for item_index in range(item_count):
                variant = variants[(index * 3 + item_index * 5) % len(variants)]
                unit_price = variant.sale_price
                quantity = rng.randint(1, 4 if order_type == Order.TYPE_B2C else 9)
                line_discount = Decimal(str(10 * item_index))
                OrderItem.objects.create(
                    order=order,
                    variant=variant,
                    quantity=quantity,
                    unit_price=unit_price,
                    discount=line_discount,
                    total=max((unit_price * quantity) - line_discount, Decimal('0')),
                )

            subtotal = sum(item.unit_price * item.quantity for item in order.items.all())
            line_discount = sum(item.discount for item in order.items.all())
            total = max(subtotal - line_discount - order.discount, Decimal('0'))
            paid_amount = total
            if index % 5 == 0:
                paid_amount = Decimal('0')
            elif index % 4 == 0:
                paid_amount = (total * Decimal('0.45')).quantize(Decimal('0.01'))

            order.subtotal = subtotal
            order.total = total
            order.paid_amount = paid_amount
            order.remaining_amount = max(total - paid_amount, Decimal('0'))
            if paid_amount <= 0:
                order.payment_status = Order.PAYMENT_UNPAID
            elif paid_amount >= total:
                order.payment_status = Order.PAYMENT_PAID
            else:
                order.payment_status = Order.PAYMENT_PARTIAL
            order.save()

            created_at = timezone.now() - timezone.timedelta(days=index % 18, hours=index % 7)
            Order.objects.filter(pk=order.pk).update(created_at=created_at, updated_at=created_at)

            if status in {Order.STATUS_CONFIRMED, Order.STATUS_PREPARING, Order.STATUS_READY, Order.STATUS_COMPLETED, Order.STATUS_RETURNED}:
                invoice, _ = Invoice.objects.update_or_create(
                    order=order,
                    defaults={
                        'invoice_number': f'INV-DEMO-{today.strftime("%Y%m")}-{index:04d}',
                        'printed_count': index % 4,
                    },
                )
                Invoice.objects.filter(pk=invoice.pk).update(issued_at=created_at + timezone.timedelta(minutes=12))
