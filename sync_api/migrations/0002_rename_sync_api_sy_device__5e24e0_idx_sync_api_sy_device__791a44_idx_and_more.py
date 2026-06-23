from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('sync_api', '0001_initial'),
    ]

    operations = [
        migrations.RenameIndex(
            model_name='syncoperation',
            new_name='sync_api_sy_device__791a44_idx',
            old_name='sync_api_sy_device__5e24e0_idx',
        ),
        migrations.RenameIndex(
            model_name='syncoperation',
            new_name='sync_api_sy_entity__bbb6b4_idx',
            old_name='sync_api_sy_entity_213305_idx',
        ),
    ]
