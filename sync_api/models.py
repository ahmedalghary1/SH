from django.conf import settings
from django.db import models


class SyncOperation(models.Model):
    STATUS_SUCCESS = 'success'
    STATUS_FAILED = 'failed'
    STATUS_CONFLICT = 'failed_conflict'
    STATUS_CHOICES = [
        (STATUS_SUCCESS, 'Success'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_CONFLICT, 'Failed conflict'),
    ]

    idempotency_key = models.CharField(max_length=160, unique=True, db_index=True)
    device_id = models.CharField(max_length=120, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    entity_type = models.CharField(max_length=40, db_index=True)
    operation_type = models.CharField(max_length=40)
    local_uuid = models.CharField(max_length=120, db_index=True)
    server_model = models.CharField(max_length=100, blank=True, null=True)
    server_object_id = models.CharField(max_length=100, blank=True, null=True)
    payload_hash = models.CharField(max_length=64, blank=True, null=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_SUCCESS, db_index=True)
    response_json = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['device_id', 'created_at']),
            models.Index(fields=['entity_type', 'local_uuid']),
        ]

    def __str__(self):
        return self.idempotency_key
