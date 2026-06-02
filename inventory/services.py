from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Stock, StockMovement


def _get_locked_stock(warehouse, variant):
    stock, _ = Stock.objects.select_for_update().get_or_create(
        warehouse=warehouse,
        variant=variant,
        defaults={'quantity': 0},
    )
    return stock


@transaction.atomic
def stock_in(*, variant, warehouse, quantity, user, note=''):
    if quantity <= 0:
        raise ValidationError('الكمية يجب أن تكون أكبر من صفر')
    stock = _get_locked_stock(warehouse, variant)
    stock.quantity += quantity
    stock.save(update_fields=['quantity'])
    return StockMovement.objects.create(
        movement_type=StockMovement.TYPE_IN,
        variant=variant,
        to_warehouse=warehouse,
        quantity=quantity,
        note=note,
        created_by=user,
    )


@transaction.atomic
def stock_out(*, variant, warehouse, quantity, user, note=''):
    if quantity <= 0:
        raise ValidationError('الكمية يجب أن تكون أكبر من صفر')
    stock = _get_locked_stock(warehouse, variant)
    if stock.quantity < quantity:
        raise ValidationError('الكمية غير متاحة')
    stock.quantity -= quantity
    stock.save(update_fields=['quantity'])
    return StockMovement.objects.create(
        movement_type=StockMovement.TYPE_OUT,
        variant=variant,
        from_warehouse=warehouse,
        quantity=quantity,
        note=note,
        created_by=user,
    )


@transaction.atomic
def transfer_stock(*, variant, from_warehouse, to_warehouse, quantity, user, note=''):
    if from_warehouse == to_warehouse:
        raise ValidationError('لا يمكن التحويل إلى نفس المخزن')
    if quantity <= 0:
        raise ValidationError('الكمية يجب أن تكون أكبر من صفر')
    source = _get_locked_stock(from_warehouse, variant)
    if source.quantity < quantity:
        raise ValidationError('الكمية غير متاحة للتحويل')
    target = _get_locked_stock(to_warehouse, variant)
    source.quantity -= quantity
    target.quantity += quantity
    source.save(update_fields=['quantity'])
    target.save(update_fields=['quantity'])
    return StockMovement.objects.create(
        movement_type=StockMovement.TYPE_TRANSFER,
        variant=variant,
        from_warehouse=from_warehouse,
        to_warehouse=to_warehouse,
        quantity=quantity,
        note=note,
        created_by=user,
    )


@transaction.atomic
def adjust_stock(*, variant, warehouse, new_quantity, user, note=''):
    if new_quantity < 0:
        raise ValidationError('لا يمكن أن تكون الكمية سالبة')
    stock = _get_locked_stock(warehouse, variant)
    diff = new_quantity - stock.quantity
    stock.quantity = new_quantity
    stock.save(update_fields=['quantity'])
    return StockMovement.objects.create(
        movement_type=StockMovement.TYPE_ADJUSTMENT,
        variant=variant,
        to_warehouse=warehouse if diff >= 0 else None,
        from_warehouse=warehouse if diff < 0 else None,
        quantity=abs(diff),
        note=note,
        created_by=user,
    )


@transaction.atomic
def sale_stock(*, variant, warehouse, quantity, user, note=''):
    stock = _get_locked_stock(warehouse, variant)
    if stock.quantity < quantity:
        raise ValidationError('الكمية غير متاحة')
    stock.quantity -= quantity
    stock.save(update_fields=['quantity'])
    return StockMovement.objects.create(
        movement_type=StockMovement.TYPE_SALE,
        variant=variant,
        from_warehouse=warehouse,
        quantity=quantity,
        note=note,
        created_by=user,
    )


@transaction.atomic
def return_stock(*, variant, warehouse, quantity, user, note=''):
    stock = _get_locked_stock(warehouse, variant)
    stock.quantity += quantity
    stock.save(update_fields=['quantity'])
    return StockMovement.objects.create(
        movement_type=StockMovement.TYPE_RETURN,
        variant=variant,
        to_warehouse=warehouse,
        quantity=quantity,
        note=note,
        created_by=user,
    )
