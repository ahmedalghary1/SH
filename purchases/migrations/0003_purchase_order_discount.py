from django.db import migrations, models


def backfill_subtotals(apps, schema_editor):
    PurchaseOrder = apps.get_model('purchases', 'PurchaseOrder')
    PurchaseOrder.objects.all().update(subtotal_amount=models.F('total_amount'))


class Migration(migrations.Migration):
    dependencies = [('purchases', '0002_purchaseorderitem_purchases_purchaseorderitem_quantity_gt_0_and_more')]
    operations = [
        migrations.AddField(model_name='purchaseorder', name='subtotal_amount', field=models.DecimalField(decimal_places=2, default=0, max_digits=14)),
        migrations.AddField(model_name='purchaseorder', name='discount_type', field=models.CharField(choices=[('fixed', 'مبلغ ثابت'), ('percent', 'نسبة مئوية')], default='fixed', max_length=10)),
        migrations.AddField(model_name='purchaseorder', name='discount_value', field=models.DecimalField(decimal_places=2, default=0, max_digits=14)),
        migrations.AddField(model_name='purchaseorder', name='discount_amount', field=models.DecimalField(decimal_places=2, default=0, max_digits=14)),
        migrations.RunPython(backfill_subtotals, migrations.RunPython.noop),
    ]
