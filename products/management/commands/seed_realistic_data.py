import random
from decimal import Decimal
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from customers.models import Customer, CustomerInteraction
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


REALISTIC_TAG = 'REALISTIC_SEED'


class Command(BaseCommand):
    help = 'Seed the database with extensive realistic dummy data'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset',
            action='store_true',
            help='Delete previously seeded realistic records before recreating them.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options['reset']:
            self._reset_realistic_data()

        self.stdout.write('Creating realistic dummy data...')
        
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
        self._seed_stock_movements(orders, variants, warehouses, users)
        self._seed_payment_transactions(orders, customers, cash_accounts, users)
        self._seed_sales_rep_assignments(users, variants, warehouses)
        self._seed_customer_interactions(customers, users)
        self._seed_sales_returns(orders, variants, users)
        self._seed_sales_rep_collections(users, customers, orders, cash_accounts)
        self._seed_expenses(cash_accounts, users)
        self._seed_adjustments(variants, warehouses, users)

        self.stdout.write(self.style.SUCCESS(
            f'Realistic data seeded: {len(variants)} variants, {len(customers)} customers, {len(orders)} orders.'
        ))

    def _reset_realistic_data(self):
        self.stdout.write('Resetting realistic data...')
        realistic_orders = Order.objects.filter(order_number__startswith='ORD-RL-')
        realistic_purchase_orders = PurchaseOrder.objects.filter(purchase_number__startswith='PO-RL-')
        realistic_variants = ProductVariant.objects.filter(variant_sku__startswith='RL-')

        ExchangeItem.objects.filter(sales_return__order__in=realistic_orders).delete()
        SalesReturnItem.objects.filter(sales_return__order__in=realistic_orders).delete()
        SalesReturn.objects.filter(order__in=realistic_orders).delete()
        Invoice.objects.filter(order__in=realistic_orders).delete()
        PaymentTransaction.objects.filter(related_order__in=realistic_orders).delete()
        PaymentTransaction.objects.filter(related_supplier__purchase_orders__in=realistic_purchase_orders).delete()
        PaymentTransaction.objects.filter(notes__contains=REALISTIC_TAG).delete()
        SalesRepCollection.objects.filter(order__in=realistic_orders).delete()
        SalesRepStockAssignment.objects.filter(product_variant__in=realistic_variants).delete()
        realistic_orders.delete()
        realistic_purchase_orders.delete()

        StockMovement.objects.filter(variant__in=realistic_variants).delete()
        StockBatch.objects.filter(variant__in=realistic_variants).delete()
        Stock.objects.filter(variant__in=realistic_variants).delete()
        realistic_variants.delete()
        Product.objects.filter(sku__startswith='RL-').delete()
        Customer.objects.filter(notes__contains=REALISTIC_TAG).delete()
        Supplier.objects.filter(notes__contains=REALISTIC_TAG).delete()
        Warehouse.objects.filter(name__startswith='RL-').delete()
        CashAccount.objects.filter(name__startswith='RL-').delete()
        CustomerInteraction.objects.filter(notes__contains=REALISTIC_TAG).delete()

    def _seed_users(self):
        users = {}
        
        # Manager
        manager, _ = User.objects.update_or_create(
            username='manager_rl',
            defaults={
                'role': User.ROLE_MANAGER,
                'is_staff': True,
                'is_superuser': True,
                'first_name': 'أحمد',
                'last_name': 'محمد',
                'phone': '0501234567',
                'email': 'manager@rl.local',
                'is_active': True,
            },
        )
        manager.set_password('manager123')
        manager.save(update_fields=['password'])
        users['manager'] = manager
        
        # Sales Reps
        sales_data = [
            ('sales1_rl', 'خالد', 'علي', '0502345678'),
            ('sales2_rl', 'سعيد', 'أحمد', '0503456789'),
            ('sales3_rl', 'عمر', 'فهد', '0504567890'),
            ('sales4_rl', 'عبدالله', 'سعود', '0505678901'),
        ]
        for username, first, last, phone in sales_data:
            user, _ = User.objects.update_or_create(
                username=username,
                defaults={
                    'role': User.ROLE_SALES,
                    'first_name': first,
                    'last_name': last,
                    'phone': phone,
                    'email': f'{username}@rl.local',
                    'is_active': True,
                },
            )
            user.set_password('sales123')
            user.save(update_fields=['password'])
            users[f'sales_{first}'] = user
        
        # Warehouse Staff
        warehouse_data = [
            ('warehouse1_rl', 'محمد', 'عبدالرحمن', '0506789012'),
            ('warehouse2_rl', 'فهد', 'القحطاني', '0507890123'),
        ]
        for username, first, last, phone in warehouse_data:
            user, _ = User.objects.update_or_create(
                username=username,
                defaults={
                    'role': User.ROLE_WAREHOUSE,
                    'first_name': first,
                    'last_name': last,
                    'phone': phone,
                    'email': f'{username}@rl.local',
                    'is_active': True,
                },
            )
            user.set_password('warehouse123')
            user.save(update_fields=['password'])
            users[f'warehouse_{first}'] = user
        
        return users

    def _seed_settings(self):
        settings = CompanySettings.load()
        settings.company_name = 'شركة الشروق للملابس الجاهزة'
        settings.phone = '0501234567'
        settings.email = 'sales@shorouk-fashion.com'
        settings.address = 'الرياض، حي الملز'
        settings.tax_number = '3000000000'
        settings.invoice_notes = 'شكرا لتعاملكم معنا. الاستبدال خلال 14 يوما بشرط سلامة المنتج.'
        settings.save()

    def _seed_cash_accounts(self, users):
        accounts = {}
        
        # Main Cash
        main_cash, _ = CashAccount.objects.update_or_create(
            name='RL-الخزنة الرئيسية',
            defaults={
                'account_type': CashAccount.TYPE_CASH,
                'balance': Decimal('500000.00'),
                'is_active': True,
            },
        )
        accounts['main_cash'] = main_cash
        
        # Bank Account
        bank, _ = CashAccount.objects.update_or_create(
            name='RL-البنك الأهلي',
            defaults={
                'account_type': CashAccount.TYPE_BANK,
                'balance': Decimal('1500000.00'),
                'is_active': True,
            },
        )
        accounts['bank'] = bank
        
        # Wallet
        wallet, _ = CashAccount.objects.update_or_create(
            name='RL-محفظة STC Pay',
            defaults={
                'account_type': CashAccount.TYPE_WALLET,
                'balance': Decimal('75000.00'),
                'is_active': True,
            },
        )
        accounts['wallet'] = wallet
        
        # Store Cash Accounts
        for i in range(3):
            account, _ = CashAccount.objects.update_or_create(
                name=f'RL-خزنة المحل {i+1}',
                defaults={
                    'account_type': CashAccount.TYPE_CASH,
                    'balance': Decimal(random.randint(20000, 100000)),
                    'is_active': True,
                },
            )
            accounts[f'store_{i+1}'] = account
        
        # Sales Rep Cash Accounts
        for i, (key, user) in enumerate([(k, v) for k, v in users.items() if 'sales' in k][:3]):
            account, _ = CashAccount.objects.update_or_create(
                name=f'RL-عهدة {user.first_name} مالية',
                defaults={
                    'account_type': CashAccount.TYPE_SALES_REP_CASH,
                    'assigned_user': user,
                    'balance': Decimal(random.randint(5000, 25000)),
                    'is_active': True,
                },
            )
            accounts[f'rep_{i+1}'] = account
        
        return accounts

    def _seed_categories(self):
        categories = {}
        
        # Main categories
        main_cats = [
            ('ملابس', None),
            ('أحذية', None),
            ('إكسسوارات', None),
        ]
        for name, parent in main_cats:
            cat, _ = Category.objects.update_or_create(
                name=name,
                defaults={'parent': parent, 'is_active': True}
            )
            categories[name] = cat
        
        # Subcategories for clothing
        clothing_sub = [
            ('ملابس رجالية', 'ملابس'),
            ('ملابس نسائية', 'ملابس'),
            ('ملابس أطفال', 'ملابس'),
        ]
        for name, parent in clothing_sub:
            cat, _ = Category.objects.update_or_create(
                name=name,
                defaults={'parent': categories[parent], 'is_active': True}
            )
            categories[name] = cat
        
        # Subcategories for shoes
        shoes_sub = [
            ('أحذية رجالية', 'أحذية'),
            ('أحذية نسائية', 'أحذية'),
        ]
        for name, parent in shoes_sub:
            cat, _ = Category.objects.update_or_create(
                name=name,
                defaults={'parent': categories[parent], 'is_active': True}
            )
            categories[name] = cat
        
        # Subcategories for accessories
        acc_sub = [
            ('حقائب', 'إكسسوارات'),
            ('ساعات', 'إكسسوارات'),
        ]
        for name, parent in acc_sub:
            cat, _ = Category.objects.update_or_create(
                name=name,
                defaults={'parent': categories[parent], 'is_active': True}
            )
            categories[name] = cat
        
        return categories

    def _seed_colors(self):
        color_data = [
            ('أسود', '#000000'),
            ('أبيض', '#FFFFFF'),
            ('أزرق', '#0000FF'),
            ('أحمر', '#FF0000'),
            ('أخضر', '#008000'),
            ('رمادي', '#808080'),
            ('بيج', '#F5F5DC'),
            ('بني', '#A52A2A'),
            ('وردي', '#FFC0CB'),
            ('بنفسجي', '#800080'),
            ('كحلي', '#000080'),
            ('فضي', '#C0C0C0'),
            ('ذهبي', '#FFD700'),
            ('برتقالي', '#FFA500'),
            ('أصفر', '#FFFF00'),
        ]
        
        colors = {}
        for name, hex_code in color_data:
            color, _ = Color.objects.update_or_create(
                name=name,
                defaults={'hex_code': hex_code}
            )
            colors[name] = color
        
        return colors

    def _seed_sizes(self):
        size_data = [
            ('XS', 1),
            ('S', 2),
            ('M', 3),
            ('L', 4),
            ('XL', 5),
            ('XXL', 6),
            ('3XL', 7),
            ('36', 10),
            ('37', 11),
            ('38', 12),
            ('39', 13),
            ('40', 14),
            ('41', 15),
            ('42', 16),
            ('43', 17),
            ('44', 18),
            ('45', 19),
            ('One Size', 20),
        ]
        
        sizes = {}
        for name, sort_order in size_data:
            size, _ = Size.objects.update_or_create(
                name=name,
                defaults={'sort_order': sort_order}
            )
            sizes[name] = size
        
        return sizes

    def _seed_products(self, categories, colors, sizes):
        variants = []
        
        product_data = [
            # Men's Clothing
            ('RL-M-SHIRT-001', 'قميص رجالي كلاسيك', 'ملابس رجالية', 'قطن 100%', 'صيف/خريف', Decimal('150.00'), Decimal('120.00'), ['أسود', 'أبيض', 'أزرق', 'رمادي'], ['S', 'M', 'L', 'XL']),
            ('RL-M-JEAN-001', 'بنطال جينز رجالي', 'ملابس رجالية', 'دينيم', 'جميع الفصول', Decimal('280.00'), Decimal('220.00'), ['أسود', 'أزرق', 'رمادي'], ['38', '40', '42', '44']),
            ('RL-M-JACKET-001', 'جاكيت رجالي شتوي', 'ملابس رجالية', 'بوليستر', 'شتاء', Decimal('450.00'), Decimal('350.00'), ['أسود', 'بني', 'كحلي'], ['M', 'L', 'XL', 'XXL']),
            ('RL-M-TSHIRT-001', 'تيشيرت رجالي قطني', 'ملابس رجالية', 'قطن', 'صيف', Decimal('80.00'), Decimal('60.00'), ['أسود', 'أبيض', 'أحمر', 'أزرق'], ['S', 'M', 'L', 'XL']),
            ('RL-M-POLO-001', 'بولو رجالي', 'ملابس رجالية', 'قطن', 'جميع الفصول', Decimal('120.00'), Decimal('95.00'), ['أبيض', 'أزرق', 'رمادي'], ['S', 'M', 'L', 'XL']),
            
            # Women's Clothing
            ('RL-W-DRESS-001', 'فستان نسائي أنيق', 'ملابس نسائية', 'حرير', 'صيف', Decimal('350.00'), Decimal('280.00'), ['أسود', 'أحمر', 'وردي'], ['S', 'M', 'L']),
            ('RL-W-BLOUSE-001', 'بلوزة نسائية', 'ملابس نسائية', 'حرير', 'جميع الفصول', Decimal('180.00'), Decimal('145.00'), ['أبيض', 'بيج', 'وردي'], ['S', 'M', 'L', 'XL']),
            ('RL-W-SKIRT-001', 'تنورة نسائية', 'ملابس نسائية', 'قطن', 'صيف', Decimal('150.00'), Decimal('120.00'), ['أسود', 'أزرق', 'رمادي'], ['S', 'M', 'L']),
            ('RL-W-JACKET-001', 'جاكيت نسائي', 'ملابس نسائية', 'صوف', 'شتاء', Decimal('550.00'), Decimal('420.00'), ['أسود', 'بني', 'كحلي'], ['S', 'M', 'L', 'XL']),
            ('RL-W-PANTS-001', 'بنطال نسائي', 'ملابس نسائية', 'قطن', 'جميع الفصول', Decimal('200.00'), Decimal('160.00'), ['أسود', 'أزرق', 'رمادي', 'بيج'], ['S', 'M', 'L', 'XL']),
            
            # Kids Clothing
            ('RL-K-TSHIRT-001', 'تيشيرت أطفال', 'ملابس أطفال', 'قطن', 'صيف', Decimal('60.00'), Decimal('45.00'), ['أزرق', 'أحمر', 'أصفر'], ['S', 'M', 'L']),
            ('RL-K-PANTS-001', 'بنطال أطفال', 'ملابس أطفال', 'قطن', 'جميع الفصول', Decimal('80.00'), Decimal('60.00'), ['أسود', 'أزرق', 'رمادي'], ['S', 'M', 'L']),
            ('RL-K-JACKET-001', 'جاكيت أطفال', 'ملابس أطفال', 'بوليستر', 'شتاء', Decimal('180.00'), Decimal('140.00'), ['أزرق', 'أحمر', 'وردي'], ['S', 'M', 'L']),
            
            # Men's Shoes
            ('RL-MS-SHOE-001', 'حذاء رجالي رسمي', 'أحذية رجالية', 'جلد طبيعي', 'جميع الفصول', Decimal('450.00'), Decimal('350.00'), ['أسود', 'بني'], ['40', '41', '42', '43', '44']),
            ('RL-MS-SNEAKER-001', 'حذاء رجالي رياضي', 'أحذية رجالية', 'قماش', 'جميع الفصول', Decimal('320.00'), Decimal('250.00'), ['أسود', 'أبيض', 'أزرق', 'رمادي'], ['40', '41', '42', '43', '44']),
            ('RL-MS-CASUAL-001', 'حذاء كاجوال رجالي', 'أحذية رجالية', 'جلد', 'جميع الفصول', Decimal('280.00'), Decimal('220.00'), ['أسود', 'بني', 'بيج'], ['40', '41', '42', '43', '44']),
            
            # Women's Shoes
            ('RL-WS-HEEL-001', 'حذاء كعب عالي', 'أحذية نسائية', 'جلد', 'جميع الفصول', Decimal('380.00'), Decimal('300.00'), ['أسود', 'أحمر', 'ذهبي'], ['36', '37', '38', '39', '40']),
            ('RL-WS-SNEAKER-001', 'حذاء نسائي رياضي', 'أحذية نسائية', 'قماش', 'جميع الفصول', Decimal('280.00'), Decimal('220.00'), ['أبيض', 'أسود', 'وردي'], ['36', '37', '38', '39', '40']),
            ('RL-WS-CASUAL-001', 'حذاء نسائي كاجوال', 'أحذية نسائية', 'جلد', 'جميع الفصول', Decimal('250.00'), Decimal('195.00'), ['أسود', 'بني', 'بيج'], ['36', '37', '38', '39', '40']),
            
            # Accessories - Bags
            ('RL-AC-HANDBAG-001', 'حقيبة يد نسائية', 'حقائب', 'جلد', 'جميع الفصول', Decimal('450.00'), Decimal('350.00'), ['أسود', 'بني', 'بيج'], ['One Size']),
            ('RL-AC-BACKPACK-001', 'حقيبة ظهر', 'حقائب', 'قماش', 'جميع الفصول', Decimal('280.00'), Decimal('220.00'), ['أسود', 'أزرق', 'رمادي'], ['One Size']),
            ('RL-AC-WALLET-001', 'محفظة جلدية', 'حقائب', 'جلد', 'جميع الفصول', Decimal('150.00'), Decimal('115.00'), ['أسود', 'بني'], ['One Size']),
            
            # Accessories - Watches
            ('RL-AC-MWATCH-001', 'ساعة رجالية كلاسيك', 'ساعات', 'معدن/جلد', 'جميع الفصول', Decimal('850.00'), Decimal('650.00'), ['أسود', 'فضي', 'ذهبي'], ['One Size']),
            ('RL-AC-WWATCH-001', 'ساعة نسائية أنيقة', 'ساعات', 'معدن', 'جميع الفصول', Decimal('680.00'), Decimal('520.00'), ['ذهبي', 'فضي', 'وردي'], ['One Size']),
            ('RL-AC-SWATCH-001', 'ساعة رياضية', 'ساعات', 'بلاستيك', 'جميع الفصول', Decimal('320.00'), Decimal('245.00'), ['أسود', 'أزرق', 'أحمر'], ['One Size']),
        ]
        
        color_codes = {name: name[:3].upper() for name in colors.keys()}
        
        for sku, name, category_name, material, season, retail_price, wholesale_price, product_colors, product_sizes in product_data:
            product, _ = Product.objects.update_or_create(
                sku=sku,
                defaults={
                    'name': name,
                    'category': categories[category_name],
                    'description': f'{name} عالي الجودة، {material}، مناسب لـ {season}',
                    'material': material,
                    'season': season,
                    'retail_price': retail_price,
                    'wholesale_price': wholesale_price,
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
                            'barcode': f'{sku}{random.randint(1000, 9999)}',
                            'cost_price': wholesale_price * Decimal('0.7'),
                            'sale_price': retail_price,
                            'is_active': True,
                        },
                    )
                    variants.append(variant)
        
        return variants

    def _seed_warehouses(self, users):
        warehouses = {}
        
        # Main Warehouse
        main, _ = Warehouse.objects.update_or_create(
            name='RL-المخزن الرئيسي - الرياض',
            defaults={
                'warehouse_type': Warehouse.TYPE_MAIN,
                'address': 'حي الملز، الرياض',
                'is_active': True,
            },
        )
        warehouses['main'] = main
        
        # Stores
        store_data = [
            ('RL-محل النسيم - الرياض', Warehouse.TYPE_STORE, 'حي النسيم، الرياض'),
            ('RL-محل العليا - الرياض', Warehouse.TYPE_STORE, 'حي العليا، الرياض'),
            ('RL-محل الخبر - الخبر', Warehouse.TYPE_STORE, 'حي الخبر، الخبر'),
        ]
        for i, (name, w_type, address) in enumerate(store_data):
            wh, _ = Warehouse.objects.update_or_create(
                name=name,
                defaults={
                    'warehouse_type': w_type,
                    'address': address,
                    'is_active': True,
                },
            )
            warehouses[f'store_{i+1}'] = wh
        
        # Sales Rep Warehouses
        sales_users = [u for k, u in users.items() if 'sales' in k]
        for i, user in enumerate(sales_users[:3]):
            wh, _ = Warehouse.objects.update_or_create(
                name=f'RL-عهدة {user.first_name} {user.last_name}',
                defaults={
                    'warehouse_type': Warehouse.TYPE_REPRESENTATIVE,
                    'assigned_user': user,
                    'is_active': True,
                },
            )
            warehouses[f'rep_{i+1}'] = wh
        
        return warehouses

    def _seed_suppliers(self):
        suppliers = []
        
        supplier_data = [
            ('شركة الأفق للتجارة', 'أحمد العلي', '0112345678', 'ahmed@horizon.com', 'الرياض، حي الملز'),
            ('مصنع النخبة للملابس', 'محمد السعيد', '0133456789', 'info@elite-factory.com', 'الدمام، الصناعية'),
            ('شركة الأمانة للأحذية', 'عبدالله الفهد', '0144567890', 'sales@amanah-shoes.com', 'جدة، الصناعية الثالثة'),
            ('مؤسسة البركة للإكسسوارات', 'خالد الراشد', '0551234567', 'alkhair@accessories.com', 'الرياض، حي الربوة'),
            ('شركة التميز للتصدير', 'سعود الدوسري', '0165678901', 'export@tamayuz.com', 'الرياض، حي العليا'),
        ]
        
        for company, name, phone, email, address in supplier_data:
            supplier, _ = Supplier.objects.update_or_create(
                phone=phone,
                defaults={
                    'name': name,
                    'company_name': company,
                    'email': email,
                    'address': address,
                    'opening_balance': Decimal(random.randint(10000, 50000)),
                    'current_balance': Decimal(random.randint(5000, 30000)),
                    'notes': REALISTIC_TAG,
                    'is_active': True,
                },
            )
            suppliers.append(supplier)
        
        return suppliers

    def _seed_purchases_and_stock(self, suppliers, variants, warehouses, users):
        main_warehouse = warehouses['main']
        today = timezone.localdate()
        
        for i, variant in enumerate(variants):
            # Create purchase order
            supplier = suppliers[i % len(suppliers)]
            quantity = random.randint(20, 100)
            unit_cost = variant.cost_price * Decimal(random.uniform(0.95, 1.05))
            
            po = create_purchase_order(
                supplier=supplier,
                status=PurchaseOrder.STATUS_ORDERED,
                order_date=today - timedelta(days=random.randint(30, 90)),
                expected_date=today - timedelta(days=random.randint(25, 85)),
                notes=f'{REALISTIC_TAG} شراء دفعة جديدة',
                items=[{'product_variant': variant, 'quantity': quantity, 'unit_cost': unit_cost.quantize(Decimal('0.01'))}],
                user=users['manager'],
            )
            po.purchase_number = f'PO-RL-{i+1:04d}'
            po.save(update_fields=['purchase_number'])
            
            # Receive the purchase order
            receive_purchase_order_items(
                purchase_order=po,
                warehouse=main_warehouse,
                received_items={po.items.first().pk: quantity},
                user=users[f'warehouse_محمد'],
                note=f'{REALISTIC_TAG} استلام الدفعة',
            )
            
            # Add stock to some stores
            for j in range(3):
                store_key = f'store_{j+1}'
                if random.random() > 0.3:
                    store_quantity = random.randint(5, 30)
                    adjust_stock(
                        variant=variant,
                        warehouse=warehouses[store_key],
                        new_quantity=store_quantity,
                        user=users[f'warehouse_فهد'],
                        note=f'{REALISTIC_TAG} رصيد افتتاحي للمحل',
                    )
            
            # Set min quantity
            for stock in Stock.objects.filter(variant=variant):
                stock.min_quantity = random.randint(5, 15)
                stock.save(update_fields=['min_quantity'])

    def _seed_customers(self, users):
        customers = []
        
        customer_data = [
            # B2C Customers
            ('محمد أحمد العلي', '0551234567', '0551234567', 'mohammed@email.com', Customer.TYPE_B2C, 'الرياض، حي الملز'),
            ('عبدالله محمد السعيد', '0552345678', '0552345678', 'abdullah@email.com', Customer.TYPE_B2C, 'الرياض، حي العليا'),
            ('خالد عبدالرحمن الفهد', '0553456789', '0553456789', 'khaled@email.com', Customer.TYPE_B2C, 'جدة، حي الروضة'),
            ('سعود أحمد الدوسري', '0554567890', '0554567890', 'saud@email.com', Customer.TYPE_B2C, 'الدمام، حي الشاطئ'),
            ('فهد محمد القحطاني', '0555678901', '0555678901', 'fahad@email.com', Customer.TYPE_B2C, 'الخبر، حي العزيزية'),
            ('ناصر عبدالله العتيبي', '0556789012', '0556789012', 'nasser@email.com', Customer.TYPE_B2C, 'الرياض، حي النسيم'),
            ('تركي سعود الشمري', '0557890123', '0557890123', 'turki@email.com', Customer.TYPE_B2C, 'الرياض، حي الربوة'),
            ('عمر خالد الحربي', '0558901234', '0558901234', 'omar@email.com', Customer.TYPE_B2C, 'جدة، حي الحمراء'),
            
            # B2B/Wholesale Customers
            ('شركة النور للتجارة', '0111234567', '0509876543', 'info@alnoor.com', Customer.TYPE_B2B, 'الرياض، حي الملز'),
            ('مؤسسة الأفق', '0112345678', '0508765432', 'horizon@business.com', Customer.TYPE_B2B, 'الرياض، حي العليا'),
            ('شركة التميز', '0113456789', '0507654321', 'tamayuz@trade.com', Customer.TYPE_B2B, 'الدمام، الصناعية'),
            ('شركة البركة', '0114567890', '0506543210', 'alberka@trade.com', Customer.TYPE_B2B, 'جدة، الصناعية'),
        ]
        
        for name, phone, whatsapp, email, c_type, address in customer_data:
            customer, _ = Customer.objects.update_or_create(
                phone=phone,
                defaults={
                    'name': name,
                    'customer_type': c_type,
                    'whatsapp': whatsapp,
                    'email': email,
                    'company_name': name if c_type == Customer.TYPE_B2B else '',
                    'tax_number': random.randint(3000000000, 3999999999) if c_type == Customer.TYPE_B2B else None,
                    'address': address,
                    'credit_limit': Decimal(random.randint(10000, 100000)) if c_type == Customer.TYPE_B2B else Decimal('0'),
                    'opening_balance': Decimal(random.randint(0, 5000)),
                    'notes': f'{REALISTIC_TAG} عميل تجريبي',
                    'is_active': True,
                    'created_by': users['manager'],
                },
            )
            customers.append(customer)
        
        return customers

    def _seed_orders(self, customers, variants, warehouses, users):
        orders = []
        sales_users = [u for k, u in users.items() if 'sales' in k]
        today = timezone.localdate()
        
        for i in range(30):
            customer = random.choice(customers)
            warehouse = random.choice([warehouses['main'], warehouses['store_1'], warehouses['store_2'], warehouses['store_3']])
            order_type = customer.customer_type if customer.customer_type in [Customer.TYPE_B2B, Customer.TYPE_B2C] else Customer.TYPE_RETAIL
            
            created_at = timezone.now() - timedelta(days=random.randint(1, 60))
            
            # Create order items - only select variants with available stock
            available_variants = [v for v in variants if Stock.objects.filter(warehouse=warehouse, variant=v, quantity__gt=0).exists()]
            if not available_variants:
                continue
                
            selected_variants = random.sample(available_variants, min(random.randint(1, 5), len(available_variants)))
            items = []
            for variant in selected_variants:
                stock = Stock.objects.get(warehouse=warehouse, variant=variant)
                qty = min(random.randint(1, 5), stock.quantity)
                if qty > 0:
                    items.append({
                        'variant': variant,
                        'warehouse': warehouse,
                        'quantity': qty,
                        'unit_price': variant.sale_price,
                    })
            
            if not items:
                continue
            
            # Create order
            order = create_order(
                order_data={
                    'document_type': random.choice([Order.DOCUMENT_SALE, Order.DOCUMENT_SALE, Order.DOCUMENT_SALE, Order.DOCUMENT_QUOTE]),
                    'order_type': order_type,
                    'customer': customer,
                    'warehouse': warehouse,
                    'payment_method': random.choice([Order.METHOD_CASH, Order.METHOD_BANK, Order.METHOD_CREDIT]),
                    'discount_amount': Decimal('0'),
                    'discount_percentage': Decimal('0'),
                    'notes': f'{REALISTIC_TAG} طلب تجريبي',
                },
                items=items,
                user=random.choice(sales_users),
                confirm=False,  # Don't confirm automatically to avoid stock issues
            )
            
            order.order_number = f'ORD-RL-{i+1:04d}'
            order.created_at = created_at
            order.updated_at = created_at
            order.save()
            
            # Update payment status
            if order.status != Order.STATUS_DRAFT and order.document_type != Order.DOCUMENT_QUOTE:
                if random.random() > 0.3:
                    order.payment_status = Order.STATUS_PAID
                    order.paid_amount = order.total
                    order.remaining_amount = Decimal('0')
                elif random.random() > 0.5:
                    order.payment_status = Order.STATUS_PARTIAL
                    order.paid_amount = order.total * Decimal(random.uniform(0.3, 0.7))
                    order.remaining_amount = order.total - order.paid_amount
                order.save()
                
                # Generate invoice for completed orders
                if order.status == Order.STATUS_COMPLETED:
                    try:
                        invoice = generate_invoice(order, user=random.choice(sales_users))
                        invoice.invoice_number = f'INV-RL-{i+1:04d}'
                        invoice.issued_at = created_at + timedelta(minutes=15)
                        invoice.save()
                    except:
                        pass
            
            orders.append(order)
        
        return orders

    def _seed_stock_movements(self, orders, variants, warehouses, users):
        completed_orders = [o for o in orders if o.status == Order.STATUS_COMPLETED]
        
        for order in completed_orders[:20]:
            for item in order.items.all():
                StockMovement.objects.create(
                    movement_type=StockMovement.TYPE_SALE,
                    variant=item.variant,
                    from_warehouse=order.warehouse,
                    to_warehouse=None,
                    batch=None,
                    quantity=item.quantity,
                    note=f'بيع للطلب {order.order_number}',
                    created_by=order.created_by,
                    created_at=order.created_at,
                )
        
        # Create some transfer movements
        for i in range(8):
            variant = random.choice(variants)
            from_wh = warehouses['main']
            to_wh = random.choice([warehouses['store_1'], warehouses['store_2'], warehouses['store_3']])
            
            StockMovement.objects.create(
                movement_type=StockMovement.TYPE_TRANSFER,
                variant=variant,
                from_warehouse=from_wh,
                to_warehouse=to_wh,
                batch=None,
                quantity=random.randint(5, 20),
                note=f'{REALISTIC_TAG} تحويل للمحل',
                created_by=users[f'warehouse_محمد'],
                created_at=timezone.now() - timedelta(days=random.randint(5, 30)),
            )

    def _seed_payment_transactions(self, orders, customers, cash_accounts, users):
        for order in orders:
            if order.paid_amount > 0:
                direction = PaymentTransaction.DIRECTION_IN
                cash_account = random.choice([cash_accounts['main_cash'], cash_accounts['bank'], cash_accounts['wallet']])
                
                PaymentTransaction.objects.create(
                    transaction_type=PaymentTransaction.TYPE_CUSTOMER_PAYMENT,
                    direction=direction,
                    amount=order.paid_amount,
                    cash_account=cash_account,
                    related_order=order,
                    related_customer=order.customer,
                    reference=order.order_number,
                    notes=f'دفعة للطلب {order.order_number}',
                    transaction_date=order.created_at.date(),
                    created_by=order.created_by,
                    created_at=order.created_at,
                )

    def _seed_sales_rep_assignments(self, users, variants, warehouses):
        sales_users = [u for k, u in users.items() if 'sales' in k]
        rep_warehouses = [warehouses[f'rep_{i+1}'] for i in range(min(3, len(warehouses)))]
        
        for i, user in enumerate(sales_users[:3]):
            if i < len(rep_warehouses):
                warehouse = rep_warehouses[i]
                main_warehouse = warehouses['main']
                
                selected_variants = random.sample(variants, random.randint(15, 30))
                
                for variant in selected_variants:
                    quantity = random.randint(5, 30)
                    SalesRepStockAssignment.objects.create(
                        sales_rep=user,
                        product_variant=variant,
                        source_warehouse=main_warehouse,
                        quantity_assigned=quantity,
                        quantity_sold=random.randint(0, quantity // 2),
                        quantity_returned=random.randint(0, 3),
                        quantity_remaining=random.randint(5, 20),
                        assigned_by=users['manager'],
                        notes=f'{REALISTIC_TAG} تعيين مبدئي',
                        is_active=True,
                    )

    def _seed_customer_interactions(self, customers, users):
        interaction_types = [
            CustomerInteraction.TYPE_CALL,
            CustomerInteraction.TYPE_WHATSAPP,
            CustomerInteraction.TYPE_VISIT,
            CustomerInteraction.TYPE_NOTE,
            CustomerInteraction.TYPE_FOLLOW_UP,
        ]
        
        for customer in customers[:10]:
            for _ in range(random.randint(2, 5)):
                CustomerInteraction.objects.create(
                    customer=customer,
                    interaction_type=random.choice(interaction_types),
                    title=random.choice([
                        'متابعة الطلب',
                        'عرض منتجات جديدة',
                        'شكوى جودة',
                        'طلب خصم',
                        'تأكيد موعد زيارة',
                        'ملاحظة عامة',
                    ]),
                    description=random.choice([
                        'العميل مهتم بالمنتجات الجديدة',
                        'تم الاتفاق على زيارة الأسبوع القادم',
                        'العميل يطلب خصم إضافي',
                        'تم حل المشكلة',
                        'العميل راضٍ عن الخدمة',
                    ]),
                    next_follow_up_date=timezone.now().date() + timedelta(days=random.randint(3, 14)) if random.random() > 0.5 else None,
                    created_by=random.choice([u for k, u in users.items() if 'sales' in k]),
                    is_completed=random.choice([True, False]),
                    created_at=timezone.now() - timedelta(days=random.randint(1, 30)),
                )

    def _seed_sales_returns(self, orders, variants, users):
        completed_orders = [o for o in orders if o.status == Order.STATUS_COMPLETED]
        
        for order in completed_orders[:6]:
            if order.items.count() > 0:
                return_order = SalesReturn.objects.create(
                    order=order,
                    customer=order.customer,
                    return_type=random.choice([
                        SalesReturn.TYPE_REFUND,
                        SalesReturn.TYPE_EXCHANGE,
                        SalesReturn.TYPE_PARTIAL_RETURN,
                    ]),
                    status=random.choice([
                        SalesReturn.STATUS_COMPLETED,
                        SalesReturn.STATUS_APPROVED,
                        SalesReturn.STATUS_DRAFT,
                    ]),
                    reason=random.choice([
                        'المقاس غير مناسب',
                        'عيب في المنتج',
                        'العميل غير راضٍ',
                        'خطأ في الطلب',
                    ]),
                    refund_amount=Decimal(random.randint(50, 500)),
                    created_by=random.choice([u for k, u in users.items() if 'sales' in k]),
                    approved_by=users['manager'] if random.random() > 0.5 else None,
                    completed_by=random.choice([u for k, u in users.items() if 'sales' in k]) if random.random() > 0.7 else None,
                    created_at=timezone.now() - timedelta(days=random.randint(1, 20)),
                )
                
                for item in random.sample(list(order.items.all()), min(2, order.items.count())):
                    SalesReturnItem.objects.create(
                        sales_return=return_order,
                        original_order_item=item,
                        product_variant=item.variant,
                        quantity=random.randint(1, item.quantity),
                        condition=random.choice([
                            SalesReturnItem.CONDITION_GOOD,
                            SalesReturnItem.CONDITION_GOOD,
                            SalesReturnItem.CONDITION_DAMAGED,
                        ]),
                        return_to_stock=True,
                        refund_amount=item.final_unit_price * random.randint(1, item.quantity),
                        notes='مرتجع عادي',
                    )

    def _seed_sales_rep_collections(self, users, customers, orders, cash_accounts):
        sales_users = [u for k, u in users.items() if 'sales' in k]
        rep_accounts = [cash_accounts.get(f'rep_{i+1}') for i in range(3) if cash_accounts.get(f'rep_{i+1}')]
        
        for i in range(10):
            user = random.choice(sales_users)
            customer = random.choice(customers)
            customer_orders = [o for o in orders if o.customer == customer]
            if not customer_orders:
                continue
            order = random.choice(customer_orders)
            account = rep_accounts[0] if rep_accounts else cash_accounts['main_cash']
            
            amount = Decimal(random.randint(500, 5000))
            
            SalesRepCollection.objects.create(
                sales_rep=user,
                customer=customer,
                order=order,
                amount=amount,
                handed_over_amount=amount if random.random() > 0.3 else Decimal('0'),
                cash_account=account,
                collection_date=timezone.now().date() - timedelta(days=random.randint(1, 30)),
                handed_over=random.choice([True, False]),
                handed_over_at=timezone.now() - timedelta(days=random.randint(1, 15)) if random.random() > 0.5 else None,
                notes=f'{REALISTIC_TAG} تحصيل تجريبي',
                created_by=users['manager'],
            )

    def _seed_expenses(self, cash_accounts, users):
        expense_types = [
            ('إيجار', Decimal(random.randint(3000, 8000))),
            ('فواتير كهرباء', Decimal(random.randint(500, 2000))),
            ('رواتب', Decimal(random.randint(10000, 30000))),
            ('صيانة', Decimal(random.randint(500, 3000))),
            ('مصاريف نقل', Decimal(random.randint(300, 1500))),
        ]
        
        for i in range(15):
            name, amount = random.choice(expense_types)
            add_expense(
                amount=amount,
                cash_account=random.choice([cash_accounts['main_cash'], cash_accounts['bank']]),
                user=users['manager'],
                notes=f'{REALISTIC_TAG} {name}',
            )

    def _seed_adjustments(self, variants, warehouses, users):
        for i in range(5):
            variant = random.choice(variants)
            warehouse = random.choice([warehouses['store_1'], warehouses['store_2'], warehouses['store_3']])
            
            adjust_stock(
                variant=variant,
                warehouse=warehouse,
                new_quantity=random.randint(5, 20),
                user=users[f'warehouse_فهد'],
                note=f'{REALISTIC_TAG} تسوية جرد',
            )
