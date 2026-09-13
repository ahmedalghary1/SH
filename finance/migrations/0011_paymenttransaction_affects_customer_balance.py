from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0010_alter_cashaccount_managers_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='paymenttransaction',
            name='affects_customer_balance',
            field=models.BooleanField(db_index=True, default=False),
        ),
    ]
