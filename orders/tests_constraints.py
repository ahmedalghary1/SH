from decimal import Decimal
from django.test import TransactionTestCase
from django.db import transaction, IntegrityError

from products.models import Product, ProductVariant, Color, Size
from customers.models import Customer
from orders.models import Order, OrderItem
from orders.services import calculate_order_totals
from finance.models import CashAccount, PaymentTransaction
from purchases.models import PurchaseOrder, PurchaseOrderItem, Supplier
from inventory.models import Warehouse


class DatabaseConstraintTests(TransactionTestCase):
    def setUp(self):
        self.warehouse = Warehouse.objects.create(name="Constraint Warehouse", warehouse_type="main")
        self.color = Color.objects.create(name="Blue")
        self.size = Size.objects.create(name="XL")
        self.product = Product.objects.create(name="Constraint Product", sku="CONST001")
        self.variant = ProductVariant.objects.create(
            product=self.product,
            color=self.color,
            size=self.size,
            variant_sku="CONST001-BLU-XL",
            cost_price=Decimal("10.00"),
            sale_price=Decimal("20.00"),
        )
        self.customer = Customer.objects.create(name="Customer Const", phone="01012345678")

    def test_product_variant_negative_cost_price(self):
        """Test ProductVariant.cost_price >= 0 constraint."""
        invalid_variant = ProductVariant(
            product=self.product,
            variant_sku="CONST-NEGATIVE-COST",
            cost_price=Decimal("-1.00"),
            sale_price=Decimal("15.00"),
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                invalid_variant.save()

    def test_product_variant_negative_sale_price(self):
        """Test ProductVariant.sale_price >= 0 constraint."""
        invalid_variant = ProductVariant(
            product=self.product,
            variant_sku="CONST-NEGATIVE-SALE",
            cost_price=Decimal("10.00"),
            sale_price=Decimal("-5.00"),
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                invalid_variant.save()

    def test_order_invalid_discount_percentage(self):
        """Test Order.discount_percentage range [0, 100] constraint."""
        order_high = Order(
            order_number="ORD-CONST-HIGH",
            order_type="b2c",
            customer=self.customer,
            warehouse=self.warehouse,
            discount_percentage=Decimal("105.00"),
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                order_high.save()

        order_neg = Order(
            order_number="ORD-CONST-NEG",
            order_type="b2c",
            customer=self.customer,
            warehouse=self.warehouse,
            discount_percentage=Decimal("-1.00"),
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                order_neg.save()

    def test_order_negative_discount_amount(self):
        """Test Order.discount_amount >= 0 constraint."""
        order = Order(
            order_number="ORD-CONST-NEG-AMT",
            order_type="b2c",
            customer=self.customer,
            warehouse=self.warehouse,
            discount_amount=Decimal("-10.00"),
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                order.save()

    def test_order_item_invalid_discount_percentage(self):
        """Test OrderItem.discount_percentage range [0, 100] constraint."""
        order = Order.objects.create(
            order_number="ORD-CONST-ITEM-PCT",
            order_type="b2c",
            customer=self.customer,
            warehouse=self.warehouse,
        )
        invalid_item = OrderItem(
            order=order,
            variant=self.variant,
            quantity=1,
            unit_price=Decimal("20.00"),
            total=Decimal("20.00"),
            discount_percentage=Decimal("110.00"),
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                invalid_item.save()

    def test_order_item_negative_discount_amount(self):
        """Test OrderItem.discount_amount >= 0 constraint."""
        order = Order.objects.create(
            order_number="ORD-CONST-ITEM-AMT",
            order_type="b2c",
            customer=self.customer,
            warehouse=self.warehouse,
        )
        invalid_item = OrderItem(
            order=order,
            variant=self.variant,
            quantity=1,
            unit_price=Decimal("20.00"),
            total=Decimal("20.00"),
            discount_amount=Decimal("-5.00"),
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                invalid_item.save()

    def test_order_item_negative_final_unit_price(self):
        """Test OrderItem.final_unit_price >= 0 constraint."""
        order = Order.objects.create(
            order_number="ORD-CONST-ITEM-PRICE",
            order_type="b2c",
            customer=self.customer,
            warehouse=self.warehouse,
        )
        invalid_item = OrderItem(
            order=order,
            variant=self.variant,
            quantity=1,
            unit_price=Decimal("20.00"),
            final_unit_price=Decimal("-1.00"),
            total=Decimal("20.00"),
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                invalid_item.save()

    def test_payment_transaction_zero_or_negative_amount(self):
        """Test PaymentTransaction.amount > 0 constraint."""
        cash = CashAccount.objects.create(name="Test Cash", balance=Decimal("100.00"))
        
        tx_zero = PaymentTransaction(
            transaction_type=PaymentTransaction.TYPE_EXPENSE,
            direction=PaymentTransaction.DIRECTION_OUT,
            amount=Decimal("0.00"),
            cash_account=cash,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                tx_zero.save()

        tx_neg = PaymentTransaction(
            transaction_type=PaymentTransaction.TYPE_EXPENSE,
            direction=PaymentTransaction.DIRECTION_OUT,
            amount=Decimal("-10.00"),
            cash_account=cash,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                tx_neg.save()

    def test_purchase_order_item_zero_or_negative_quantity(self):
        """Test PurchaseOrderItem.quantity > 0 constraint."""
        supplier = Supplier.objects.create(name="Test Supplier")
        po = PurchaseOrder.objects.create(
            purchase_number="PO-CONST-001",
            supplier=supplier,
        )
        item_zero = PurchaseOrderItem(
            purchase_order=po,
            product_variant=self.variant,
            quantity=0,
            unit_cost=Decimal("10.00"),
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                item_zero.save()

    def test_purchase_order_item_negative_unit_cost(self):
        """Test PurchaseOrderItem.unit_cost >= 0 constraint."""
        supplier = Supplier.objects.create(name="Test Supplier")
        po = PurchaseOrder.objects.create(
            purchase_number="PO-CONST-002",
            supplier=supplier,
        )
        invalid_item = PurchaseOrderItem(
            purchase_order=po,
            product_variant=self.variant,
            quantity=5,
            unit_cost=Decimal("-1.00"),
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                invalid_item.save()

    def test_calculate_order_totals_transaction_safety(self):
        """Test that calculate_order_totals requires an active transaction block."""
        order = Order.objects.create(
            order_number="ORD-CONST-SAFETY",
            order_type="b2c",
            customer=self.customer,
            warehouse=self.warehouse,
        )
        
        # Should raise RuntimeError when called outside transaction
        with self.assertRaises(RuntimeError) as ctx:
            calculate_order_totals(order)
        self.assertIn("calculate_order_totals must be called within an active transaction", str(ctx.exception))
        
        # Should succeed inside a transaction block
        with transaction.atomic():
            calculate_order_totals(order)
