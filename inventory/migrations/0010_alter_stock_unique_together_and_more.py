from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0009_alter_stockmovement_movement_type'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='stock',
            unique_together=set(),
        ),
        migrations.AddConstraint(
            model_name='stock',
            constraint=models.UniqueConstraint(
                fields=('warehouse', 'variant'),
                name='stock_warehouse_variant_unique',
            ),
        ),
    ]
