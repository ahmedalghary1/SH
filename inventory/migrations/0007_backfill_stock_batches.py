from django.db import migrations


def create_opening_batches(apps, schema_editor):
    Stock = apps.get_model('inventory', 'Stock')
    StockBatch = apps.get_model('inventory', 'StockBatch')
    for stock in Stock.objects.select_related('variant', 'warehouse').filter(quantity__gt=0):
        if StockBatch.objects.filter(variant_id=stock.variant_id, warehouse_id=stock.warehouse_id).exists():
            continue
        StockBatch.objects.create(
            variant_id=stock.variant_id,
            warehouse_id=stock.warehouse_id,
            received_quantity=stock.quantity,
            remaining_quantity=stock.quantity,
            unit_cost=stock.variant.cost_price or 0,
            source='opening_balance',
            note='Opening stock batch generated from current stock',
        )


def remove_opening_batches(apps, schema_editor):
    StockBatch = apps.get_model('inventory', 'StockBatch')
    StockBatch.objects.filter(source='opening_balance').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0006_alter_stockmovement_movement_type_stockbatch_and_more'),
    ]

    operations = [
        migrations.RunPython(create_opening_batches, remove_opening_batches),
    ]
