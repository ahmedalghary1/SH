from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from accounts.models import User
from finance.models import CashAccount, PaymentTransaction
from finance.services import record_transaction
from inventory.models import Stock, StockMovement
from orders.models import Order

from .models import SalesRepCollection, SalesRepStockAssignment


def _validate_sales_rep(user):
    if not user or getattr(user, 'role', None) != User.ROLE_SALES:
        raise ValidationError('اختر مستخدما بدور مندوب مبيعات')


def get_or_create_sales_rep_cash_account(sales_rep):
    _validate_sales_rep(sales_rep)
    account, _ = CashAccount.objects.get_or_create(
        account_type=CashAccount.TYPE_SALES_REP_CASH,
        assigned_user=sales_rep,
        defaults={'name': f'عهدة نقدية - {sales_rep.get_full_name() or sales_rep.username}', 'is_active': True},
    )
    return account


@transaction.atomic
def assign_stock_to_sales_rep(*, sales_rep, product_variant, source_warehouse, quantity, assigned_by, notes=''):
    _validate_sales_rep(sales_rep)
    quantity = int(quantity)
    if quantity <= 0:
        raise ValidationError('كمية التسليم يجب أن تكون أكبر من صفر')
    stock = Stock.objects.select_for_update().filter(warehouse=source_warehouse, variant=product_variant).first()
    if not stock or stock.quantity < quantity:
        raise ValidationError('الكمية غير متاحة في المخزن')
    stock.quantity = F('quantity') - quantity
    stock.save(update_fields=['quantity'])

    assignment = SalesRepStockAssignment.objects.select_for_update().filter(
        sales_rep=sales_rep,
        product_variant=product_variant,
        source_warehouse=source_warehouse,
        is_active=True,
    ).first()
    if not assignment:
        assignment = SalesRepStockAssignment.objects.create(
            sales_rep=sales_rep,
            product_variant=product_variant,
            source_warehouse=source_warehouse,
            assigned_by=assigned_by,
            notes=notes,
        )
    assignment.quantity_assigned = F('quantity_assigned') + quantity
    assignment.quantity_remaining = F('quantity_remaining') + quantity
    assignment.assigned_by = assigned_by
    assignment.notes = notes or assignment.notes
    assignment.save(update_fields=['quantity_assigned', 'quantity_remaining', 'assigned_by', 'notes', 'updated_at'])
    assignment.refresh_from_db(fields=['quantity_assigned', 'quantity_remaining'])

    StockMovement.objects.create(
        movement_type=StockMovement.TYPE_SALES_REP_ASSIGNMENT,
        variant=product_variant,
        from_warehouse=source_warehouse,
        quantity=quantity,
        note=notes or f'Sales rep assignment to {sales_rep}',
        created_by=assigned_by,
    )
    return assignment


@transaction.atomic
def return_stock_from_sales_rep(*, assignment, quantity, user, notes=''):
    quantity = int(quantity)
    if quantity <= 0:
        raise ValidationError('كمية الرجوع يجب أن تكون أكبر من صفر')
    assignment = SalesRepStockAssignment.objects.select_for_update().select_related('source_warehouse', 'product_variant').get(pk=assignment.pk)
    if quantity > assignment.quantity_remaining:
        raise ValidationError('كمية الرجوع أكبر من المتبقي مع المندوب')
    stock, _ = Stock.objects.select_for_update().get_or_create(
        warehouse=assignment.source_warehouse,
        variant=assignment.product_variant,
        defaults={'quantity': 0},
    )
    stock.quantity = F('quantity') + quantity
    stock.save(update_fields=['quantity'])
    assignment.quantity_remaining = F('quantity_remaining') - quantity
    assignment.quantity_returned = F('quantity_returned') + quantity
    if assignment.quantity_remaining == 0:
        assignment.is_active = False
    assignment.save(update_fields=['quantity_remaining', 'quantity_returned', 'is_active', 'updated_at'])
    assignment.refresh_from_db(fields=['quantity_remaining', 'quantity_returned'])
    StockMovement.objects.create(
        movement_type=StockMovement.TYPE_SALES_REP_RETURN,
        variant=assignment.product_variant,
        to_warehouse=assignment.source_warehouse,
        quantity=quantity,
        note=notes or f'Sales rep return from {assignment.sales_rep}',
        created_by=user,
    )
    return assignment


@transaction.atomic
def record_sales_rep_sale(*, assignment, quantity, user, order=None, notes=''):
    quantity = int(quantity)
    if quantity <= 0:
        raise ValidationError('كمية البيع يجب أن تكون أكبر من صفر')
    assignment = SalesRepStockAssignment.objects.select_for_update().select_related('product_variant').get(pk=assignment.pk)
    if quantity > assignment.quantity_remaining:
        raise ValidationError('كمية البيع أكبر من عهدة المندوب')
    assignment.quantity_remaining = F('quantity_remaining') - quantity
    assignment.quantity_sold = F('quantity_sold') + quantity
    if assignment.quantity_remaining == 0:
        assignment.is_active = False
    assignment.save(update_fields=['quantity_remaining', 'quantity_sold', 'is_active', 'updated_at'])
    assignment.refresh_from_db(fields=['quantity_remaining', 'quantity_sold'])
    StockMovement.objects.create(
        movement_type=StockMovement.TYPE_SALES_REP_SALE,
        variant=assignment.product_variant,
        quantity=quantity,
        note=notes or f'Sales rep sale {assignment.sales_rep}',
        created_by=user,
    )
    return assignment


@transaction.atomic
def record_sales_rep_collection(*, sales_rep, amount, user, cash_account=None, customer=None, order=None, notes=''):
    _validate_sales_rep(sales_rep)
    amount = Decimal(str(amount or 0))
    if amount <= 0:
        raise ValidationError('مبلغ التحصيل يجب أن يكون أكبر من صفر')
    if order:
        order = Order.objects.select_for_update().get(pk=order.pk)
        if amount > order.remaining_amount:
            raise ValidationError('مبلغ التحصيل أكبر من المتبقي على الطلب')
        customer = customer or order.customer
    cash_account = cash_account or get_or_create_sales_rep_cash_account(sales_rep)
    collection = SalesRepCollection.objects.create(
        sales_rep=sales_rep,
        customer=customer,
        order=order,
        amount=amount,
        cash_account=cash_account,
        notes=notes,
        created_by=user,
    )
    record_transaction(
        transaction_type=PaymentTransaction.TYPE_SALES_REP_COLLECTION,
        direction=PaymentTransaction.DIRECTION_IN,
        amount=amount,
        cash_account=cash_account,
        related_order=order,
        related_customer=customer,
        related_sales_rep=sales_rep,
        notes=notes or f'Sales rep collection {sales_rep}',
        created_by=user,
    )
    if order:
        order.paid_amount = F('paid_amount') + amount
        order.save(update_fields=['paid_amount'])
        order.refresh_from_db(fields=['paid_amount'])
        order.remaining_amount = max(order.total - order.paid_amount, Decimal('0'))
        if order.paid_amount <= 0:
            order.payment_status = Order.PAYMENT_UNPAID
        elif order.paid_amount >= order.total:
            order.payment_status = Order.PAYMENT_PAID
        else:
            order.payment_status = Order.PAYMENT_PARTIAL
        order.save(update_fields=['remaining_amount', 'payment_status'])
    return collection


@transaction.atomic
def handover_sales_rep_cash(*, sales_rep, amount, target_cash_account, user, source_cash_account=None, notes=''):
    _validate_sales_rep(sales_rep)
    amount = Decimal(str(amount or 0))
    if amount <= 0:
        raise ValidationError('مبلغ التسليم يجب أن يكون أكبر من صفر')
    source_cash_account = source_cash_account or get_or_create_sales_rep_cash_account(sales_rep)
    collections = SalesRepCollection.objects.select_for_update().filter(
        sales_rep=sales_rep,
        cash_account=source_cash_account,
        handed_over=False,
    ).order_by('collection_date', 'created_at')
    available = sum((collection.remaining_handover_amount for collection in collections), Decimal('0'))
    if amount > available:
        raise ValidationError('مبلغ التسليم أكبر من التحصيلات غير المسلمة')

    reference = f'SRH-{timezone.now().strftime("%Y%m%d%H%M%S")}-{sales_rep.pk}'
    record_transaction(
        transaction_type=PaymentTransaction.TYPE_SALES_REP_HANDOVER,
        direction=PaymentTransaction.DIRECTION_OUT,
        amount=amount,
        cash_account=source_cash_account,
        related_sales_rep=sales_rep,
        notes=notes or f'Sales rep handover from {sales_rep}',
        created_by=user,
        reference=reference,
    )
    record_transaction(
        transaction_type=PaymentTransaction.TYPE_SALES_REP_HANDOVER,
        direction=PaymentTransaction.DIRECTION_IN,
        amount=amount,
        cash_account=target_cash_account,
        related_sales_rep=sales_rep,
        notes=notes or f'Sales rep handover to management from {sales_rep}',
        created_by=user,
        reference=reference,
    )

    remaining = amount
    for collection in collections:
        if remaining <= 0:
            break
        portion = min(collection.remaining_handover_amount, remaining)
        collection.handed_over_amount = F('handed_over_amount') + portion
        collection.save(update_fields=['handed_over_amount'])
        collection.refresh_from_db(fields=['handed_over_amount'])
        if collection.handed_over_amount >= collection.amount:
            collection.handed_over = True
            collection.handed_over_at = timezone.now()
            collection.save(update_fields=['handed_over', 'handed_over_at', 'updated_at'])
        remaining -= portion
    return amount


def get_sales_rep_statement(sales_rep):
    _validate_sales_rep(sales_rep)
    assignments = SalesRepStockAssignment.objects.filter(sales_rep=sales_rep)
    collections = SalesRepCollection.objects.filter(sales_rep=sales_rep)
    return {
        'assigned_quantity': assignments.aggregate(v=Sum('quantity_assigned'))['v'] or 0,
        'sold_quantity': assignments.aggregate(v=Sum('quantity_sold'))['v'] or 0,
        'returned_quantity': assignments.aggregate(v=Sum('quantity_returned'))['v'] or 0,
        'remaining_quantity': assignments.aggregate(v=Sum('quantity_remaining'))['v'] or 0,
        'collected_amount': collections.aggregate(v=Sum('amount'))['v'] or Decimal('0'),
        'handed_over_amount': collections.aggregate(v=Sum('handed_over_amount'))['v'] or Decimal('0'),
        'unhanded_amount': sum((collection.remaining_handover_amount for collection in collections), Decimal('0')),
        'assignments': assignments.select_related('product_variant__product', 'source_warehouse').order_by('-created_at'),
        'collections': collections.select_related('customer', 'order', 'cash_account').order_by('-created_at'),
    }
