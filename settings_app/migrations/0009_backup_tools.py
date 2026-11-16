import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('settings_app', '0008_alter_companysettings_managers_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='BackupIdentity',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('uid', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('model_label', models.CharField(max_length=100)),
                ('object_pk', models.CharField(max_length=100)),
                ('is_primary', models.BooleanField(default=False)),
            ],
        ),
        migrations.AddIndex(
            model_name='backupidentity',
            index=models.Index(fields=['model_label', 'object_pk'], name='settings_ap_model_l_5fa9bf_idx'),
        ),
        migrations.AddConstraint(
            model_name='backupidentity',
            constraint=models.UniqueConstraint(fields=('model_label', 'object_pk'), condition=models.Q(is_primary=True),
                                              name='backup_one_primary_identity'),
        ),
        migrations.CreateModel(
            name='BackupBranchHistory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('digest', models.CharField(max_length=64)),
                ('ancestors', models.JSONField(default=list)),
                ('branch', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to='accounts.branch')),
            ],
        ),
        migrations.CreateModel(
            name='BackupImport',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('original_name', models.CharField(max_length=255)),
                ('archive_digest', models.CharField(max_length=64)),
                ('preview_digest', models.CharField(max_length=64)),
                ('summary', models.JSONField(default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
