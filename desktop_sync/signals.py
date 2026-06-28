import uuid

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from customers.models import Customer
from orders.models import Order

from .models import SyncEntityMap, SyncOutbox
from .services import build_customer_payload, build_order_payload
from .state import is_importing


def _desktop_enabled():
    return bool(getattr(settings, 'DESKTOP_LOCAL_MODE', False))


def _ensure_map(entity_type, instance):
    mapped, _ = SyncEntityMap.objects.get_or_create(
        entity_type=entity_type,
        local_object_id=str(instance.pk),
        defaults={
            'local_uuid': f'{entity_type}-{uuid.uuid4()}',
            'server_object_id': '',
            'is_server_origin': False,
        },
    )
    return mapped


def _queue_create(entity_type, instance, payload_builder):
    if not _desktop_enabled() or is_importing() or not instance.pk:
        return
    mapped = _ensure_map(entity_type, instance)
    if mapped.server_object_id or mapped.is_server_origin:
        return

    def enqueue():
        SyncOutbox.objects.update_or_create(
            entity_type=entity_type,
            operation_type='create',
            local_object_id=str(instance.pk),
            defaults={
                'local_uuid': mapped.local_uuid,
                'payload': payload_builder(instance),
                'status': SyncOutbox.STATUS_PENDING,
                'created_by': getattr(instance, 'created_by', None),
            },
        )

    transaction.on_commit(enqueue)


@receiver(post_save, sender=Customer)
def queue_customer_sync(sender, instance, created, **kwargs):
    if created:
        _queue_create('customer', instance, build_customer_payload)


@receiver(post_save, sender=Order)
def queue_order_sync(sender, instance, created, **kwargs):
    if created:
        _queue_create('order', instance, build_order_payload)
