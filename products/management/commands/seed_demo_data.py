from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from customers.models import Customer
from finance.models import CashAccount, PaymentTransaction
from finance.services import add_expense
from inventory.models import Stock, StockBatch, StockMovement, Warehouse
from inventory.services import adjust_stock
from invoices.models import Invoice
from invoices.services import generate_invoice
from orders.models import Order
from orders.services import confirm_order, create_order
from products.models import Category, Color, Product, ProductVariant, Size
from purchases.models import PurchaseOrder, Supplier
from purchases.services import create_purchase_order, receive_purchase_order_items
from returns.models import ExchangeItem, SalesReturn, SalesReturnItem
from sales_reps.models import SalesRepCollection, SalesRepStockAssignment
from settings_app.models import CompanySettings


DEMO_TAG = 'DEMO_SEED'


class Command(BaseCommand):
    help = 'Reset old fake data and seed realistic demo data for the updated ERP.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset-demo',
            action='store_true',
            help='Delete previously seeded demo records before recreating them.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options['reset_demo']:
            self._reset_demo_data()

        users = self._seed_users()
        self._seed_settings()
        cash_accounts = self._seed_cash_accounts(users)
        categories = self._seed_categories()
        colors = self._seed_colors()
        sizes = self._seed_sizes()
        variants = self._seed_products(categories, colors, sizes)
        warehouses = self._seed_warehouses(users)
        suppliers = self._seed_suppliers()
        self._seed_purchases_and_stock(suppliers, variants, warehouses, users)
        customers = self._seed_customers(users)
        orders = self._seed_orders(customers, variants, warehouses, users)
        self._seed_adjustments(variants, warehouses, users)
        self._seed_expenses(cash_accounts, users)

        self.stdout.write(self.style.SUCCESS(
            f'Demo data refreshed: {len(variants)} variants, {len(customers)} customers, {len(orders)} sales documents.'
        ))

    def _reset_demo_data(self):
        demo_orders = Order.objects.filter(order_number__startswith='ORD-DEMO-')
        demo_purchase_orders = PurchaseOrder.objects.filter(purchase_number__startswith='PO-DEMO-')
        demo_variants = ProductVariant.objects.filter(variant_sku__startswith='DEMO-')

        ExchangeItem.objects.filter(sales_return__order__in=demo_orders).delete()
        SalesReturnItem.objects.filter(sales_return__order__in=demo_orders).delete()
        SalesReturn.objects.filter(order__in=demo_orders).delete()
        Invoice.objects.filter(order__in=demo_orders).delete()
        PaymentTransaction.objects.filter(related_order__in=demo_orders).delete()
        PaymentTransaction.objects.filter(related_supplier__purchase_orders__in=demo_purchase_orders).delete()
        PaymentTransaction.objects.filter(notes__contains=DEMO_TAG).delete()
        SalesRepCollection.objects.filter(order__in=demo_orders).delete()
        SalesRepStockAssignment.objects.filter(product_variant__in=demo_variants).delete()
        demo_orders.delete()
        demo_purchase_orders.delete()

        StockMovement.objects.filter(variant__in=demo_variants).delete()
        StockBatch.objects.filter(variant__in=demo_variants).delete()
        Stock.objects.filter(variant__in=demo_variants).delete()
        demo_variants.delete()
        Product.objects.filter(sku__startswith='DEMO-').delete()
        Customer.objects.filter(notes__contains=DEMO_TAG).delete()
        Supplier.objects.filter(notes__contains=DEMO_TAG).delete()
        Warehouse.objects.filter(name__startswith='DEMO - ').delete()
        CashAccount.objects.filter(name__startswith='DEMO - ').delete()

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
                'email': 'admin@demo.local',
                'is_active': True,
            },
        )
        manager.set_password('admin12345')
        manager.save(update_fields=['password'])

        warehouse_user, _ = User.objects.update_or_create(
            username='warehouse',
            defaults={
                'role': User.ROLE_WAREHOUSE,
                'first_name': 'كريم',
                'last_name': 'فؤاد',
                'phone': '01005554444',
                'email': 'warehouse@demo.local',
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
                'email': 'ahmed.sales@demo.local',
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
                'email': 'sara.sales@demo.local',
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

    def _seed_settings(self):
        settings = CompanySettings.load()
        settings.company_name = 'شركة الشروق للملابس الجاهزة'
        settings.phone = '0100 445 7788'
        settings.email = 'sales@shorouk-fashion.demo'
        settings.address = '18 شارع التحرير، الدقي، الجيزة'
        settings.tax_number = 'EG-563-884-219'
        settings.invoice_notes = 'شكرا لتعاملكم معنا. الاستبدال خلال 14 يوما بشرط سلامة المنتج.'
        settings.save()

    def _seed_cash_accounts(self, users):
        default_cash = CashAccount.get_default()
        default_cash.balance = Decimal('0.00')
        default_cash.is_active = True
        default_cash.save(update_fields=['balance', 'is_active'])

        bank, _ = CashAccount.objects.update_or_create(
            name='DEMO - حساب بنك مصر',
            defaults={
                'account_type': CashAccount.TYPE_BANK,
                'balance': Decimal('150000.00'),
                'allow_overdraft': False,
                'is_active': True,
            },
        )
        wallet, _ = CashAccount.objects.update_or_create(
            name='DEMO - محفظة الشركة',
            defaults={
                'account_type': CashAccount.TYPE_WALLET,
                'balance': Decimal('25000.00'),
                'allow_overdraft': False,
                'is_active': True,
            },
        )
        rep_cash, _ = CashAccount.objects.update_or_create(
            name='DEMO - عهدة أحمد النقدية',
            defaults={
                'account_type': CashAccount.TYPE_SALES_REP_CASH,
                'assigned_user': users['sales_ahmed'],
                'balance': Decimal('0.00'),
                'allow_overdraft': False,
                'is_active': True,
            },
        )
        return {'default': default_cash, 'bank': bank, 'wallet': wallet, 'rep_cash': rep_cash}

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
        return {name: Color.objects.update_or_create(name=name, defaults={'hex_code': hex_code})[0] for name, hex_code in data}

    def _seed_sizes(self):
        data = [('S', 1), ('M', 2), ('L', 3), ('XL', 4), ('XXL', 5), ('38', 6), ('40', 7), ('42', 8)]
        return {name: Size.objects.update_or_create(name=name, defaults={'sort_order': order})[0] for name, order in data}

    def _seed_products(self, categories, colors, sizes):
        product_data = [
            ('DEMO-SH-001', 'قميص أوكسفورد رجالي', 'قمصان', 'قطن أوكسفورد', Decimal('560'), ['أبيض', 'كحلي'], ['M', 'L', 'XL']),
            ('DEMO-TS-002', 'تيشيرت قطن مطبوع', 'تيشيرتات', 'قطن 100%', Decimal('340'), ['أسود', 'أبيض', 'زيتوني'], ['S', 'M', 'L']),
            ('DEMO-TR-003', 'بنطلون تشينو Slim Fit', 'بناطيل', 'قماش تشينو', Decimal('720'), ['بيج', 'كحلي', 'أسود'], ['38', '40', '42']),
            ('DEMO-DR-004', 'فستان صيفي كتان', 'فساتين', 'كتان مخلوط', Decimal('920'), ['أحمر', 'بيج'], ['S', 'M', 'L']),
            ('DEMO-JK-005', 'جاكيت جينز خفيف', 'جاكيتات', 'جينز قطني', Decimal('1280'), ['كحلي', 'أسود'], ['M', 'L']),
            ('DEMO-AC-006', 'حزام جلد كلاسيك', 'إكسسوارات', 'جلد صناعي فاخر', Decimal('295'), ['أسود', 'بيج'], ['M', 'L']),
        ]

        variants = []
        color_codes = {'أبيض': 'WHT', 'أسود': 'BLK', 'كحلي': 'NVY', 'بيج': 'BEG', 'زيتوني': 'OLV', 'أحمر': 'RED', 'لبني': 'SKY'}
        for sku, name, category_name, material, sale_price, product_colors, product_sizes in product_data:
            product, _ = Product.objects.update_or_create(
                sku=sku,
                defaults={
                    'name': name,
                    'category': categories[category_name],
                    'description': f'{name} مناسب للبيع اليومي والجملة مع تتبع دفعات أسعار الشراء.',
                    'material': material,
                    'season': 'كل المواسم',
                    'retail_price': sale_price,
                    'wholesale_price': sale_price - Decimal('80'),
                    'is_active': True,
                },
            )
            for color_name in product_colors:
                for size_name in product_sizes:
                    variant_sku = f'{sku}-{color_codes[color_name]}-{size_name}'
                    variant, _ = ProductVariant.objects.update_or_create(
                        variant_sku=variant_sku,
                        defaults={
                            'product': product,
                            'color': colors[color_name],
                            'size': sizes[size_name],
                            'barcode': f'622{abs(hash(variant_sku)) % 1000000000:09d}',
                            'cost_price': sale_price - Decimal('190'),
                            'sale_price': sale_price,
                            'is_active': True,
                        },
                    )
                    variants.append(variant)
        return variants

    def _seed_warehouses(self, users):
        data = [
            ('DEMO - المخزن الرئيسي', Warehouse.TYPE_MAIN, None, 'العبور - المنطقة الصناعية'),
            ('DEMO - فرع مدينة نصر', Warehouse.TYPE_STORE, None, 'عباس العقاد - مدينة نصر'),
            ('DEMO - فرع المعادي', Warehouse.TYPE_STORE, None, 'شارع النصر - المعادي'),
            ('DEMO - عهدة أحمد سمير', Warehouse.TYPE_REPRESENTATIVE, users['sales_ahmed'], 'شرق القاهرة'),
            ('DEMO - عهدة سارة محمود', Warehouse.TYPE_REPRESENTATIVE, users['sales_sara'], 'الجيزة'),
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

    def _seed_suppliers(self):
        data = [
            ('مصنع دلتا للملابس', '01120010001', 'Delta Apparel Factory', 'المحلة الكبرى'),
            ('شركة النيل للتوريدات', '01120010002', 'Nile Garments Supply', 'شبرا الخيمة'),
            ('مكتب كتان ستايل', '01120010003', 'Linen Style Office', 'العاشر من رمضان'),
        ]
        suppliers = []
        for name, phone, company, address in data:
            supplier, _ = Supplier.objects.update_or_create(
                phone=phone,
                defaults={
                    'name': name,
                    'company_name': company,
                    'email': f'{phone}@supplier.demo',
                    'address': address,
                    'opening_balance': Decimal('0.00'),
                    'current_balance': Decimal('0.00'),
                    'notes': DEMO_TAG,
                    'is_active': True,
                },
            )
            suppliers.append(supplier)
        return suppliers

    def _seed_purchases_and_stock(self, suppliers, variants, warehouses, users):
        main = warehouses['DEMO - المخزن الرئيسي']
        branch_nasr = warehouses['DEMO - فرع مدينة نصر']
        branch_maadi = warehouses['DEMO - فرع المعادي']
        rep_ahmed = warehouses['DEMO - عهدة أحمد سمير']
        today = timezone.localdate()

        for index, variant in enumerate(variants):
            old_cost = variant.sale_price - Decimal('210')
            new_cost = variant.sale_price - Decimal('175')
            variant.cost_price = new_cost
            variant.save(update_fields=['cost_price'])

            old_po = create_purchase_order(
                supplier=suppliers[index % len(suppliers)],
                status=PurchaseOrder.STATUS_ORDERED,
                order_date=today - timezone.timedelta(days=45),
                expected_date=today - timezone.timedelta(days=40),
                notes=f'{DEMO_TAG} دفعة سعر قديم',
                items=[{'product_variant': variant, 'quantity': 18 + index % 5, 'unit_cost': old_cost}],
                user=users['manager'],
            )
            old_po.purchase_number = f'PO-DEMO-OLD-{index + 1:04d}'
            old_po.save(update_fields=['purchase_number'])
            receive_purchase_order_items(
                purchase_order=old_po,
                warehouse=main,
                received_items={old_po.items.first().pk: old_po.items.first().quantity},
                user=users['warehouse'],
                note=f'{DEMO_TAG} استلام دفعة قديمة',
            )

            new_po = create_purchase_order(
                supplier=suppliers[(index + 1) % len(suppliers)],
                status=PurchaseOrder.STATUS_ORDERED,
                order_date=today - timezone.timedelta(days=12),
                expected_date=today - timezone.timedelta(days=8),
                notes=f'{DEMO_TAG} دفعة سعر جديد',
                items=[{'product_variant': variant, 'quantity': 20 + index % 7, 'unit_cost': new_cost}],
                user=users['manager'],
            )
            new_po.purchase_number = f'PO-DEMO-NEW-{index + 1:04d}'
            new_po.save(update_fields=['purchase_number'])
            receive_purchase_order_items(
                purchase_order=new_po,
                warehouse=main,
                received_items={new_po.items.first().pk: new_po.items.first().quantity},
                user=users['warehouse'],
                note=f'{DEMO_TAG} استلام دفعة جديدة',
            )

            for warehouse, qty in ((branch_nasr, 5 + index % 4), (branch_maadi, 4 + index % 3), (rep_ahmed, 2 + index % 2)):
                adjust_stock(
                    variant=variant,
                    warehouse=warehouse,
                    new_quantity=qty,
                    user=users['warehouse'],
                    note=f'{DEMO_TAG} رصيد افتتاحي للفرع',
                )

            for stock in Stock.objects.filter(variant=variant):
                stock.min_quantity = 4 if stock.warehouse.warehouse_type == Warehouse.TYPE_MAIN else 2
                stock.save(update_fields=['min_quantity'])

    def _seed_customers(self, users):
        data = [
            ('محمد عبد الرحمن', Customer.TYPE_B2C, '01090010001', '', 'مدينة نصر، القاهرة'),
            ('منة خالد', Customer.TYPE_B2C, '01090010002', '', 'المعادي، القاهرة'),
            ('أحمد الشناوي', Customer.TYPE_B2C, '01090010003', '', 'الهرم، الجيزة'),
            ('نوران ياسر', Customer.TYPE_B2C, '01090010004', '', 'التجمع الخامس، القاهرة'),
            ('مؤسسة الندى للتجارة', Customer.TYPE_B2B, '01090010005', 'الندى للتجارة', 'طنطا، الغربية'),
            ('بوتيك روز', Customer.TYPE_B2B, '01090010006', 'Rose Boutique', 'المنصورة، الدقهلية'),
        ]
        customers = []
        for index, (name, customer_type, phone, company, address) in enumerate(data, start=1):
            customer, _ = Customer.objects.update_or_create(
                phone=phone,
                defaults={
                    'name': name,
                    'customer_type': customer_type,
                    'whatsapp': phone,
                    'email': f'customer{index}@demo.local',
                    'company_name': company or None,
                    'tax_number': f'TAX-DEMO-{index:03d}' if customer_type == Customer.TYPE_B2B else None,
                    'address': address,
                    'notes': f'{DEMO_TAG} عميل تجريبي مناسب لشاشات البيع والتقارير',
                    'is_active': True,
                    'created_by': users['manager'],
                },
            )
            customers.append(customer)
        return customers

    def _choose_batch(self, variant, warehouse, newest=False):
        ordering = '-received_at' if newest else 'received_at'
        return StockBatch.objects.filter(variant=variant, warehouse=warehouse, remaining_quantity__gt=0).order_by(ordering, 'pk').first()

    def _seed_orders(self, customers, variants, warehouses, users):
        main = warehouses['DEMO - المخزن الرئيسي']
        branch_nasr = warehouses['DEMO - فرع مدينة نصر']
        branch_maadi = warehouses['DEMO - فرع المعادي']
        rep_ahmed = warehouses['DEMO - عهدة أحمد سمير']
        today = timezone.localdate()
        created_orders = []

        scenarios = [
            {
                'number': 'ORD-DEMO-SALE-0001',
                'customer': customers[0],
                'warehouse': branch_nasr,
                'user': users['sales_ahmed'],
                'variant_indexes': [0, 4],
                'document_type': Order.DOCUMENT_SALE,
                'confirm': True,
                'discount_amount': Decimal('25.00'),
                'newest_batch': False,
                'days_ago': 6,
            },
            {
                'number': 'ORD-DEMO-SALE-0002',
                'customer': customers[4],
                'warehouse': main,
                'user': users['sales_sara'],
                'variant_indexes': [9, 12, 15],
                'document_type': Order.DOCUMENT_SALE,
                'confirm': True,
                'discount_percentage': Decimal('5.00'),
                'newest_batch': True,
                'days_ago': 3,
            },
            {
                'number': 'ORD-DEMO-QUOTE-0001',
                'customer': customers[1],
                'warehouse': branch_maadi,
                'user': users['sales_ahmed'],
                'variant_indexes': [2, 7],
                'document_type': Order.DOCUMENT_QUOTE,
                'confirm': False,
                'discount_amount': Decimal('40.00'),
                'days_ago': 1,
            },
            {
                'number': 'ORD-DEMO-SAMPLE-0001',
                'customer': customers[5],
                'warehouse': main,
                'user': users['manager'],
                'variant_indexes': [5],
                'document_type': Order.DOCUMENT_SAMPLE,
                'confirm': True,
                'days_ago': 2,
            },
            {
                'number': 'ORD-DEMO-REP-0001',
                'customer': customers[2],
                'warehouse': rep_ahmed,
                'user': users['sales_ahmed'],
                'variant_indexes': [1],
                'document_type': Order.DOCUMENT_SALE,
                'confirm': True,
                'days_ago': 0,
            },
        ]

        for scenario in scenarios:
            items = []
            for line_index, variant_index in enumerate(scenario['variant_indexes'], start=1):
                variant = variants[variant_index % len(variants)]
                batch = self._choose_batch(variant, scenario['warehouse'], newest=scenario.get('newest_batch', False))
                items.append({
                    'variant': variant,
                    'warehouse': scenario['warehouse'],
                    'stock_batch': batch,
                    'quantity': 1 + line_index,
                    'unit_price': variant.sale_price,
                })
            order = create_order(
                order_data={
                    'document_type': scenario['document_type'],
                    'order_type': Order.TYPE_B2B if scenario['customer'].customer_type == Customer.TYPE_B2B else Order.TYPE_B2C,
                    'customer': scenario['customer'],
                    'warehouse': scenario['warehouse'],
                    'payment_method': Order.METHOD_CASH,
                    'discount_amount': scenario.get('discount_amount', Decimal('0.00')),
                    'discount_percentage': scenario.get('discount_percentage', Decimal('0.00')),
                    'notes': f'{DEMO_TAG} سيناريو بيانات تجريبية بعد تحديث النظام',
                },
                items=items,
                user=scenario['user'],
                confirm=scenario['confirm'],
            )
            order.order_number = scenario['number']
            order.save(update_fields=['order_number'])
            created_at = timezone.now() - timezone.timedelta(days=scenario['days_ago'], hours=scenario['days_ago'])
            Order.objects.filter(pk=order.pk).update(created_at=created_at, updated_at=created_at)

            if order.status != Order.STATUS_DRAFT and order.document_type != Order.DOCUMENT_QUOTE:
                invoice = generate_invoice(order, user=scenario['user'])
                invoice.invoice_number = scenario['number'].replace('ORD-DEMO', 'INV-DEMO')
                invoice.save(update_fields=['invoice_number'])
                Invoice.objects.filter(pk=invoice.pk).update(issued_at=created_at + timezone.timedelta(minutes=15))
            created_orders.append(order)

        quote = Order.objects.get(order_number='ORD-DEMO-QUOTE-0001')
        self.stdout.write(f'Created quote without stock deduction: {quote.order_number}')
        return created_orders

    def _seed_adjustments(self, variants, warehouses, users):
        adjust_stock(
            variant=variants[3],
            warehouse=warehouses['DEMO - فرع مدينة نصر'],
            new_quantity=3,
            user=users['warehouse'],
            note=f'{DEMO_TAG} تسوية جرد يومية لمنتج سريع الحركة',
        )

    def _seed_expenses(self, cash_accounts, users):
        add_expense(
            amount=Decimal('850.00'),
            cash_account=cash_accounts['default'],
            user=users['manager'],
            notes=f'{DEMO_TAG} مصروف شحن داخلي لطلبات اليوم',
        )
