from django.core.validators import MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0008_productvariant_image'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='pieces_per_dozen',
            field=models.PositiveIntegerField(default=12, validators=[MinValueValidator(1)]),
        ),
    ]
