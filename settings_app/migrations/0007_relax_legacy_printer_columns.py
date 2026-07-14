from django.db import migrations


def relax_legacy_printer_columns(apps, schema_editor):
    """Allow ORM inserts when obsolete printer columns remain in PostgreSQL.

    These columns belonged to an older deployment and are not represented in
    the current Django model. Keeping them nullable preserves any old values
    while preventing each NOT NULL column from breaking CompanySettings.load().
    """
    connection = schema_editor.connection
    if connection.vendor != "postgresql":
        return

    model = apps.get_model("settings_app", "CompanySettings")
    table_name = model._meta.db_table
    model_columns = {field.column for field in model._meta.local_fields}

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name, is_nullable
            FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = %s
            """,
            [table_name],
        )
        legacy_columns = [
            name
            for name, is_nullable in cursor.fetchall()
            if name.startswith("printer_")
            and name not in model_columns
            and is_nullable == "NO"
        ]

    quoted_table = schema_editor.quote_name(table_name)
    for column_name in legacy_columns:
        quoted_column = schema_editor.quote_name(column_name)
        schema_editor.execute(
            f"ALTER TABLE {quoted_table} ALTER COLUMN {quoted_column} DROP NOT NULL"
        )


class Migration(migrations.Migration):
    dependencies = [
        ("settings_app", "0006_repair_legacy_printer_bottom_margin"),
    ]

    operations = [
        migrations.RunPython(relax_legacy_printer_columns, migrations.RunPython.noop),
    ]
