from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):
    dependencies = [('orders', '0010_alter_order_managers_alter_orderitem_managers_and_more')]
    operations = [migrations.AddField(
        model_name='order', name='discount_input_amount',
        field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True,
                                  validators=[django.core.validators.MinValueValidator(0)]),
    )]
