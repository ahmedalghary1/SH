from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_alter_user_role'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='username',
            field=models.CharField(error_messages={'unique': 'يوجد مستخدم بهذا الاسم بالفعل.'}, help_text='يمكن استخدام الحروف والأرقام والمسافات.', max_length=150, unique=True, verbose_name='اسم المستخدم'),
        ),
    ]
