from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0012_remove_product_supplier'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='agent',
            field=models.CharField(blank=True, max_length=200, null=True),
        ),
    ]
