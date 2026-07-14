from django.db import migrations


LEGACY_COLUMN = "printer_bottom_margin"


def repair_legacy_printer_bottom_margin(apps, schema_editor):
    """Give the legacy, unmanaged printer column a database default.

    Some production databases still contain this column from an older build,
    while it is no longer part of the Django model state.  PostgreSQL therefore
    rejects ORM inserts because the column is NOT NULL and has no default.
    """
    connection = schema_editor.connection
    table_name = apps.get_model("settings_app", "CompanySettings")._meta.db_table

    with connection.cursor() as cursor:
        columns = {
            column.name
            for column in connection.introspection.get_table_description(cursor, table_name)
        }

    if LEGACY_COLUMN not in columns:
        return

    quoted_table = schema_editor.quote_name(table_name)
    quoted_column = schema_editor.quote_name(LEGACY_COLUMN)

    if connection.vendor == "postgresql":
        schema_editor.execute(
            f"UPDATE {quoted_table} SET {quoted_column} = 0 "
            f"WHERE {quoted_column} IS NULL"
        )
        schema_editor.execute(
            f"ALTER TABLE {quoted_table} ALTER COLUMN {quoted_column} SET DEFAULT 0"
        )
        schema_editor.execute(
            f"ALTER TABLE {quoted_table} ALTER COLUMN {quoted_column} SET NOT NULL"
        )


class Migration(migrations.Migration):
    dependencies = [
        ("settings_app", "0005_companysettings_thermal_invoice_font_scale"),
    ]

    operations = [
        migrations.RunPython(repair_legacy_printer_bottom_margin, migrations.RunPython.noop),
    ]
