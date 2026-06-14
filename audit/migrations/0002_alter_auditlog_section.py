# Generated manually to keep audit section choices in migration state.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('audit', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='auditlog',
            name='section',
            field=models.CharField(
                choices=[
                    ('products', 'المنتجات'),
                    ('orders', 'الطلبات'),
                    ('inventory', 'المخزون'),
                    ('purchases', 'المشتريات'),
                    ('returns', 'المرتجعات'),
                    ('finance', 'المالية'),
                    ('customers', 'العملاء'),
                    ('sales_reps', 'المندوبين'),
                    ('settings', 'الإعدادات'),
                    ('accounts', 'الحسابات'),
                    ('invoices', 'الفواتير'),
                ],
                db_index=True,
                max_length=20,
            ),
        ),
    ]
