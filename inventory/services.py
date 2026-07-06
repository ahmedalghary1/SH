from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F

from audit.models import AuditLog
from audit.services import log_audit

from .models import Stock, StockBatch, StockMovement


def _get_locked_stock(warehouse, variant):
    stock, _ = Stock.objects.select_for_update().get_or_create(
        warehouse=warehouse,
        variant=variant,
        defaults={'quantity': 0},
    )
    return stock


def _create_batch(*, variant, warehouse, quantity, unit_cost=0, source='', note='', user=None):
    if quantity <= 0:
        return None
    return StockBatch.objects.create(
        variant=variant,
        warehouse=warehouse,
        received_quantity=quantity,
        remaining_quantity=quantity,
        unit_cost=unit_cost or 0,
        source=source,
        note=note,
        created_by=user,
    )


def _consume_batches(*, variant, warehouse, quantity, batch=None):
    if batch:
        batch = StockBatch.objects.select_for_update().get(pk=batch.pk)
        if batch.variant_id != variant.id or batch.warehouse_id != warehouse.id:
            raise ValidationError('دفعة المخزون لا تخص هذا المنتج أو المخزن')
        if batch.remaining_quantity < quantity:
            raise ValidationError('الكمية غير متاحة في دفعة السعر المختارة')
        batch.remaining_quantity = F('remaining_quantity') - quantity
        batch.save(update_fields=['remaining_quantity'])
        batch.refresh_from_db(fields=['remaining_quantity'])
        return batch

    remaining = quantity
    first_consumed = None
    batches = StockBatch.objects.select_for_update().filter(
        variant=variant,
        warehouse=warehouse,
        remaining_quantity__gt=0,
    ).order_by('received_at', 'pk')
    for stock_batch in batches:
        take = min(remaining, stock_batch.remaining_quantity)
        stock_batch.remaining_quantity = F('remaining_quantity') - take
        stock_batch.save(update_fields=['remaining_quantity'])
        stock_batch.refresh_from_db(fields=['remaining_quantity'])
        first_consumed = first_consumed or stock_batch
        remaining -= take
        if remaining <= 0:
            break
    return first_consumed


@transaction.atomic
def stock_in(*, variant, warehouse, quantity, user, note='', unit_cost=None, source='manual_in', movement_type=StockMovement.TYPE_IN):
    if quantity <= 0:
        raise ValidationError('الكمية يجب أن تكون أكبر من صفر')
    stock = _get_locked_stock(warehouse, variant)
    old_quantity = stock.quantity
    stock.quantity = F('quantity') + quantity
    stock.save(update_fields=['quantity'])
    stock.refresh_from_db(fields=['quantity'])
    batch = _create_batch(
        variant=variant,
        warehouse=warehouse,
        quantity=quantity,
        unit_cost=unit_cost if unit_cost is not None else getattr(variant, 'cost_price', 0),
        source=source,
        note=note,
        user=user,
    )
    movement = StockMovement.objects.create(
        movement_type=movement_type,
        variant=variant,
        to_warehouse=warehouse,
        batch=batch,
        quantity=quantity,
        note=note,
        created_by=user,
    )
    
    log_audit(
        user=user,
        action=AuditLog.ACTION_CREATE,
        section=AuditLog.SECTION_INVENTORY,
        model_name='StockMovement',
        object_id=movement.pk,
        object_repr=str(movement),
        changes_before={'quantity': old_quantity},
        changes_after={'quantity': stock.quantity},
        notes=f'دخول مخزون: {variant} في {warehouse} - الكمية: {quantity}',
    )
    
    return movement


@transaction.atomic
def stock_out(*, variant, warehouse, quantity, user, note='', batch=None):
    if quantity <= 0:
        raise ValidationError('الكمية يجب أن تكون أكبر من صفر')
    stock = _get_locked_stock(warehouse, variant)
    if stock.quantity < quantity:
        raise ValidationError('الكمية غير متاحة')
    old_quantity = stock.quantity
    stock.quantity = F('quantity') - quantity
    stock.save(update_fields=['quantity'])
    stock.refresh_from_db(fields=['quantity'])
    consumed_batch = _consume_batches(variant=variant, warehouse=warehouse, quantity=quantity, batch=batch)
    movement = StockMovement.objects.create(
        movement_type=StockMovement.TYPE_OUT,
        variant=variant,
        from_warehouse=warehouse,
        batch=consumed_batch,
        quantity=quantity,
        note=note,
        created_by=user,
    )
    
    log_audit(
        user=user,
        action=AuditLog.ACTION_CREATE,
        section=AuditLog.SECTION_INVENTORY,
        model_name='StockMovement',
        object_id=movement.pk,
        object_repr=str(movement),
        changes_before={'quantity': old_quantity},
        changes_after={'quantity': stock.quantity},
        notes=f'خروج مخزون: {variant} من {warehouse} - الكمية: {quantity}',
    )
    
    return movement


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
    source_old_quantity = source.quantity
    target_old_quantity = target.quantity
    source.quantity = F('quantity') - quantity
    target.quantity = F('quantity') + quantity
    source.save(update_fields=['quantity'])
    target.save(update_fields=['quantity'])
    source.refresh_from_db(fields=['quantity'])
    target.refresh_from_db(fields=['quantity'])
    source_batch = _consume_batches(variant=variant, warehouse=from_warehouse, quantity=quantity)
    target_batch = None
    if source_batch:
        target_batch = _create_batch(
            variant=variant,
            warehouse=to_warehouse,
            quantity=quantity,
            unit_cost=source_batch.unit_cost,
            source='transfer',
            note=note,
            user=user,
        )
    movement = StockMovement.objects.create(
        movement_type=StockMovement.TYPE_TRANSFER,
        variant=variant,
        from_warehouse=from_warehouse,
        to_warehouse=to_warehouse,
        batch=target_batch or source_batch,
        quantity=quantity,
        note=note,
        created_by=user,
    )
    
    log_audit(
        user=user,
        action=AuditLog.ACTION_TRANSFER,
        section=AuditLog.SECTION_INVENTORY,
        model_name='StockMovement',
        object_id=movement.pk,
        object_repr=str(movement),
        changes_before={
            'from_warehouse_quantity': source_old_quantity,
            'to_warehouse_quantity': target_old_quantity,
        },
        changes_after={
            'from_warehouse_quantity': source.quantity,
            'to_warehouse_quantity': target.quantity,
        },
        notes=f'تحويل مخزون: {variant} من {from_warehouse} إلى {to_warehouse} - الكمية: {quantity}',
    )
    
    return movement


@transaction.atomic
def adjust_stock(*, variant, warehouse, new_quantity, user, note=''):
    if new_quantity < 0:
        raise ValidationError('لا يمكن أن تكون الكمية سالبة')
    stock = _get_locked_stock(warehouse, variant)
    old_quantity = stock.quantity
    diff = new_quantity - stock.quantity
    stock.quantity = new_quantity
    stock.save(update_fields=['quantity'])
    batch = None
    if diff > 0:
        batch = _create_batch(
            variant=variant,
            warehouse=warehouse,
            quantity=diff,
            unit_cost=getattr(variant, 'cost_price', 0),
            source='adjustment',
            note=note,
            user=user,
        )
    elif diff < 0:
        batch = _consume_batches(variant=variant, warehouse=warehouse, quantity=abs(diff))
    movement = StockMovement.objects.create(
        movement_type=StockMovement.TYPE_ADJUSTMENT,
        variant=variant,
        to_warehouse=warehouse if diff >= 0 else None,
        from_warehouse=warehouse if diff < 0 else None,
        batch=batch,
        quantity=abs(diff),
        note=note,
        created_by=user,
    )
    
    log_audit(
        user=user,
        action=AuditLog.ACTION_ADJUST,
        section=AuditLog.SECTION_INVENTORY,
        model_name='StockMovement',
        object_id=movement.pk,
        object_repr=str(movement),
        changes_before={'quantity': old_quantity},
        changes_after={'quantity': new_quantity},
        notes=f'تسوية مخزون: {variant} في {warehouse} - الكمية الجديدة: {new_quantity}',
    )
    
    return movement


@transaction.atomic
def sale_stock(*, variant, warehouse, quantity, user, note='', batch=None, movement_type=StockMovement.TYPE_SALE):
    stock = _get_locked_stock(warehouse, variant)
    if stock.quantity < quantity:
        raise ValidationError('الكمية غير متاحة')
    old_quantity = stock.quantity
    stock.quantity = F('quantity') - quantity
    stock.save(update_fields=['quantity'])
    stock.refresh_from_db(fields=['quantity'])
    consumed_batch = _consume_batches(variant=variant, warehouse=warehouse, quantity=quantity, batch=batch)
    movement = StockMovement.objects.create(
        movement_type=movement_type,
        variant=variant,
        from_warehouse=warehouse,
        batch=consumed_batch,
        quantity=quantity,
        note=note,
        created_by=user,
    )
    
    log_audit(
        user=user,
        action=AuditLog.ACTION_CREATE,
        section=AuditLog.SECTION_INVENTORY,
        model_name='StockMovement',
        object_id=movement.pk,
        object_repr=str(movement),
        changes_before={'quantity': old_quantity},
        changes_after={'quantity': stock.quantity},
        notes=f'بيع مخزون: {variant} من {warehouse} - الكمية: {quantity}',
    )
    
    return movement


@transaction.atomic
def return_stock(*, variant, warehouse, quantity, user, note='', unit_cost=None):
    stock = _get_locked_stock(warehouse, variant)
    old_quantity = stock.quantity
    stock.quantity = F('quantity') + quantity
    stock.save(update_fields=['quantity'])
    stock.refresh_from_db(fields=['quantity'])
    batch = _create_batch(
        variant=variant,
        warehouse=warehouse,
        quantity=quantity,
        unit_cost=unit_cost if unit_cost is not None else getattr(variant, 'cost_price', 0),
        source='return',
        note=note,
        user=user,
    )
    movement = StockMovement.objects.create(
        movement_type=StockMovement.TYPE_RETURN,
        variant=variant,
        to_warehouse=warehouse,
        batch=batch,
        quantity=quantity,
        note=note,
        created_by=user,
    )
    
    log_audit(
        user=user,
        action=AuditLog.ACTION_RETURN,
        section=AuditLog.SECTION_INVENTORY,
        model_name='StockMovement',
        object_id=movement.pk,
        object_repr=str(movement),
        changes_before={'quantity': old_quantity},
        changes_after={'quantity': stock.quantity},
        notes=f'مرتجع مخزون: {variant} إلى {warehouse} - الكمية: {quantity}',
    )
    
    return movement
