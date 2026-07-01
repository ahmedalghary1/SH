# Generated manually on 2026-07-01

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('customers', '0003_alter_customer_customer_type'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='customer',
            name='sales_representative',
            field=models.ForeignKey(
                blank=True,
                db_index=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='assigned_customers',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddIndex(
            model_name='customer',
            index=models.Index(fields=['sales_representative', 'is_active'], name='customers_c_sales__e469cc_idx'),
        ),
    ]
