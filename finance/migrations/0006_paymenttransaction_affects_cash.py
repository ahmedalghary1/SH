from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0005_paymenttransaction_finance_pay_transac_735410_idx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='paymenttransaction',
            name='affects_cash',
            field=models.BooleanField(db_index=True, default=True),
        ),
    ]
