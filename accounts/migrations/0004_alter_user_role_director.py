from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_alter_user_username'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='role',
            field=models.CharField(
                choices=[
                    ('manager', 'مسؤول النظام'),
                    ('director', 'المدير'),
                    ('sales', 'مندوب مبيعات'),
                    ('warehouse', 'مسؤول مخزن'),
                ],
                db_index=True,
                default='sales',
                max_length=20,
            ),
        ),
    ]
