from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='SyncOperation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('idempotency_key', models.CharField(db_index=True, max_length=160, unique=True)),
                ('device_id', models.CharField(db_index=True, max_length=120)),
                ('entity_type', models.CharField(db_index=True, max_length=40)),
                ('operation_type', models.CharField(max_length=40)),
                ('local_uuid', models.CharField(db_index=True, max_length=120)),
                ('server_model', models.CharField(blank=True, max_length=100, null=True)),
                ('server_object_id', models.CharField(blank=True, max_length=100, null=True)),
                ('payload_hash', models.CharField(blank=True, max_length=64, null=True)),
                ('status', models.CharField(choices=[('success', 'Success'), ('failed', 'Failed'), ('failed_conflict', 'Failed conflict')], db_index=True, default='success', max_length=30)),
                ('response_json', models.JSONField(default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'indexes': [
                    models.Index(fields=['device_id', 'created_at'], name='sync_api_sy_device__5e24e0_idx'),
                    models.Index(fields=['entity_type', 'local_uuid'], name='sync_api_sy_entity_213305_idx'),
                ],
            },
        ),
    ]
