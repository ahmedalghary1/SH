from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0008_alter_stock_min_quantity_alter_stock_quantity_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='stockmovement',
            name='movement_type',
            field=models.CharField(choices=[('in', 'دخول مخزون'), ('out', 'خروج مخزون'), ('transfer', 'تحويل بين مخازن'), ('sale', 'بيع'), ('return', 'مرتجع'), ('adjustment', 'تسوية'), ('purchase_receive', 'استلام شراء'), ('purchase_return', 'مرتجع شراء'), ('sales_return', 'مرتجع بيع'), ('damaged_return', 'مرتجع تالف'), ('exchange_out', 'خروج استبدال'), ('sales_rep_assignment', 'تهيئة مندوب'), ('sales_rep_return', 'مرتجع مندوب'), ('sales_rep_sale', 'بيع مندوب'), ('sample', 'عينة / إصدار مجاني')], db_index=True, max_length=20),
        ),
    ]
