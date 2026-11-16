"""Protect business history from destructive catalog/account deletions."""
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.db.models.signals import pre_delete
from django.dispatch import receiver


@receiver(pre_delete, dispatch_uid='protect_business_history')
def protect_business_history(sender, instance, using, **kwargs):
    label = sender._meta.label_lower
    if label not in {'products.product', 'products.productvariant', 'customers.customer',
                     'inventory.warehouse', 'inventory.stock'}:
        return
    from finance.models import PaymentTransaction
    from inventory.models import Stock, StockBatch, StockMovement
    from orders.models import Order, OrderItem
    blocked = False
    if label in {'products.product', 'products.productvariant'}:
        key = {'variant__product_id': instance.pk} if label == 'products.product' else {'variant_id': instance.pk}
        blocked = (StockMovement.all_objects.using(using).filter(**key).exists()
                   or StockBatch.all_objects.using(using).filter(**key).exists()
                   or OrderItem.all_objects.using(using).filter(**key).exists()
                   or Stock.all_objects.using(using).filter(**key).exclude(quantity=0).exists())
    elif label == 'customers.customer':
        blocked = (instance.opening_balance != 0
                   or Order.all_objects.using(using).filter(customer_id=instance.pk).exists()
                   or PaymentTransaction.all_objects.using(using).filter(related_customer_id=instance.pk).exists())
    elif label == 'inventory.warehouse':
        blocked = (StockMovement.all_objects.using(using).filter(Q(from_warehouse_id=instance.pk) | Q(to_warehouse_id=instance.pk)).exists()
                   or StockBatch.all_objects.using(using).filter(warehouse_id=instance.pk).exists()
                   or Stock.all_objects.using(using).filter(warehouse_id=instance.pk).exclude(quantity=0).exists()
                   or Order.all_objects.using(using).filter(warehouse_id=instance.pk).exists()
                   or OrderItem.all_objects.using(using).filter(warehouse_id=instance.pk).exists())
    elif label == 'inventory.stock':
        key = {'warehouse_id': instance.warehouse_id, 'variant_id': instance.variant_id}
        blocked = (instance.quantity != 0 or StockBatch.all_objects.using(using).filter(**key).exists()
                   or StockMovement.all_objects.using(using).filter(variant_id=instance.variant_id).filter(
                       Q(from_warehouse_id=instance.warehouse_id) | Q(to_warehouse_id=instance.warehouse_id)).exists())
    if blocked:
        raise ProtectedError('هذا السجل له رصيد أو تاريخ حركات؛ عطّله بدل حذفه لحفظ المخزون والحسابات.', [instance])
