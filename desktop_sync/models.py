import uuid

from django.conf import settings
from django.db import models


def new_uuid():
    return str(uuid.uuid4())


class DesktopSyncConfig(models.Model):
    DEFAULT_REMOTE_URL = 'https://sh.elwsamstore.com/api/'

    remote_api_url = models.URLField(default=DEFAULT_REMOTE_URL)
    device_id = models.CharField(max_length=120, default=new_uuid, unique=True)
    token = models.TextField(blank=True)
    username = models.CharField(max_length=150, blank=True)
    last_pull_at = models.DateTimeField(null=True, blank=True)
    last_push_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    is_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def normalized_api_url(self):
        url = (self.remote_api_url or self.DEFAULT_REMOTE_URL).strip()
        if not url.endswith('/'):
            url += '/'
        return url


class SyncEntityMap(models.Model):
    ENTITY_CUSTOMER = 'customer'
    ENTITY_ORDER = 'order'
    ENTITY_CHOICES = [
        (ENTITY_CUSTOMER, 'Customer'),
        (ENTITY_ORDER, 'Order'),
    ]

    entity_type = models.CharField(max_length=40, choices=ENTITY_CHOICES, db_index=True)
    local_uuid = models.CharField(max_length=120, db_index=True)
    local_object_id = models.CharField(max_length=100, db_index=True)
    server_object_id = models.CharField(max_length=100, blank=True, db_index=True)
    is_server_origin = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['entity_type', 'local_object_id'], name='desktop_sync_entity_local_unique'),
            models.UniqueConstraint(fields=['entity_type', 'local_uuid'], name='desktop_sync_entity_uuid_unique'),
        ]


class SyncOutbox(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_SYNCED = 'synced'
    STATUS_FAILED = 'failed'
    STATUS_CONFLICT = 'conflict'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_SYNCED, 'Synced'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_CONFLICT, 'Conflict'),
    ]

    idempotency_key = models.CharField(max_length=160, default=new_uuid, unique=True)
    entity_type = models.CharField(max_length=40, db_index=True)
    operation_type = models.CharField(max_length=40, default='create')
    local_uuid = models.CharField(max_length=120, db_index=True)
    local_object_id = models.CharField(max_length=100, db_index=True)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    response_json = models.JSONField(default=dict)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['entity_type', 'local_uuid']),
        ]
