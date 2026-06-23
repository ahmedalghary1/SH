from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0006_paymenttransaction_affects_cash'),
    ]

    operations = [
        migrations.AlterField(
            model_name='paymenttransaction',
            name='transaction_type',
            field=models.CharField(
                choices=[
                    ('customer_payment', 'تحصيل من عميل'),
                    ('supplier_payment', 'دفع لمورد'),
                    ('expense', 'مصروف'),
                    ('refund', 'استرداد للعميل'),
                    ('sales_rep_collection', 'تحصيل مندوب'),
                    ('sales_rep_handover', 'تسليم مندوب'),
                    ('transfer', 'تحويل بين الخزن'),
                    ('adjustment', 'تسوية رصيد'),
                    ('customer_allowed_discount', 'خصم مسموح لعميل'),
                ],
                db_index=True,
                max_length=40,
            ),
        ),
    ]
