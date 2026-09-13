from django.db import migrations, models


def populate_invoice_snapshots(apps, schema_editor):
    Invoice = apps.get_model('invoices', 'Invoice')
    CompanySettings = apps.get_model('settings_app', 'CompanySettings')
    company = CompanySettings.objects.order_by('pk').first()
    company_data = {
        'name': getattr(company, 'company_name', '') or '',
        'phone': getattr(company, 'phone', '') or '',
        'email': getattr(company, 'email', '') or '',
        'address': getattr(company, 'address', '') or '',
        'tax_number': getattr(company, 'tax_number', '') or '',
        'invoice_notes': getattr(company, 'invoice_notes', '') or '',
    }
    for invoice in Invoice.objects.select_related('order__customer').iterator():
        order = invoice.order
        items = []
        for item in order.items.select_related(
            'variant__product', 'variant__color', 'variant__size', 'warehouse',
        ):
            variant = item.variant
            items.append({
                'product_name': variant.product.name if variant else 'صنف محذوف',
                'sku': variant.product.sku if variant else '',
                'variant_sku': variant.variant_sku if variant else '',
                'color': str(variant.color or '-') if variant else '-',
                'size': str(variant.size or '-') if variant else '-',
                'warehouse': str(item.warehouse or '-'),
                'quantity': item.quantity,
                'unit_price': str(item.unit_price),
                'discount': str(item.discount),
                'total': str(item.total),
            })
        customer = order.customer
        snapshot = {
            'customer_name': str(customer) if customer else 'عميل نقدي',
            'customer_phone': customer.phone if customer else '',
            'company': company_data,
            'items': items,
        }
        Invoice.objects.filter(pk=invoice.pk).update(snapshot=snapshot)


class Migration(migrations.Migration):

    dependencies = [
        ('invoices', '0002_alter_invoice_managers_invoice_branch_and_more'),
        ('settings_app', '0008_alter_companysettings_managers_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoice',
            name='snapshot',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.RunPython(populate_invoice_snapshots, migrations.RunPython.noop),
    ]
