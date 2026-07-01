# Generated manually on 2026-07-01

from django.db import migrations, models


def normalize_customer_types(apps, schema_editor):
    Customer = apps.get_model('customers', 'Customer')
    Customer.objects.filter(customer_type__in=['b2b', 'wholesale']).update(customer_type='wholesale')
    Customer.objects.exclude(customer_type='wholesale').update(customer_type='retail')


def restore_legacy_customer_types(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('customers', '0004_customer_sales_representative'),
    ]

    operations = [
        migrations.RunPython(normalize_customer_types, restore_legacy_customer_types),
        migrations.AlterField(
            model_name='customer',
            name='customer_type',
            field=models.CharField(
                choices=[
                    ('retail', 'قطاعي'),
                    ('wholesale', 'جملة'),
                ],
                db_index=True,
                default='retail',
                max_length=30,
            ),
        ),
    ]
