from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [('finance', '0008_paymenttransaction_updated_at')]
    operations = [
        migrations.AddField(model_name='paymenttransaction', name='transaction_time', field=models.TimeField(db_index=True, default=django.utils.timezone.localtime)),
    ]
