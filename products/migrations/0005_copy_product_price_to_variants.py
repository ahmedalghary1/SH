from django.db import migrations


def copy_product_price_to_variants(apps, schema_editor):
    ProductVariant = apps.get_model('products', 'ProductVariant')
    for variant in ProductVariant.objects.select_related('product').filter(sale_price=0):
        variant.sale_price = variant.product.retail_price or 0
        variant.save(update_fields=['sale_price'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0004_alter_product_retail_price_and_more'),
    ]

    operations = [
        migrations.RunPython(copy_product_price_to_variants, noop),
    ]
