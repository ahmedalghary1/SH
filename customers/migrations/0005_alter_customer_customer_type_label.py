# Generated manually on 2026-07-01

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('customers', '0004_customer_sales_representative'),
    ]

    operations = [
        migrations.AlterField(
            model_name='customer',
            name='customer_type',
            field=models.CharField(
                choices=[
                    ('b2c', 'عميل فردي'),
                    ('b2b', 'عميل جملة تجاري'),
                    ('retail', 'قطاعي'),
                    ('wholesale', 'جملة'),
                    ('inactive', 'غير نشط'),
                    ('potential', 'محتمل'),
                    ('problem_customer', 'عميل يحتاج متابعة'),
                ],
                db_index=True,
                default='retail',
                max_length=30,
            ),
        ),
    ]
