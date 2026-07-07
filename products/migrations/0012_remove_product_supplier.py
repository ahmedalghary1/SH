from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0011_product_updated_at_productvariant_updated_at'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='product',
            name='supplier',
        ),
    ]
