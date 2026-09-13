from django.db import models

from orders.models import Order
from config.branching import BranchOwnedModel


class Invoice(BranchOwnedModel):
    branch_relations = ('order',)
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='invoice')
    invoice_number = models.CharField(max_length=50, db_index=True)
    issued_at = models.DateTimeField(auto_now_add=True, db_index=True)
    printed_count = models.PositiveIntegerField(default=0)
    snapshot = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return self.invoice_number

    class Meta:
        constraints = [models.UniqueConstraint(fields=['branch', 'invoice_number'], name='invoices_invoice_branch_number_unique')]

    def infer_branch_id(self):
        return self.order.branch_id if self.order_id else None

    @property
    def customer_display(self):
        return self.snapshot.get('customer_name') or str(self.order.customer or 'عميل نقدي')

    @property
    def snapshot_items(self):
        items = self.snapshot.get('items') or []
        if items:
            return items
        return [
            {
                'product_name': item.variant.product.name if item.variant_id else 'صنف محذوف',
                'sku': item.variant.product.sku if item.variant_id else '',
                'color': str(item.variant.color or '-') if item.variant_id else '-',
                'size': str(item.variant.size or '-') if item.variant_id else '-',
                'warehouse': str(item.warehouse_or_sales_rep or '-'),
                'quantity': item.quantity,
                'unit_price': str(item.unit_price),
                'discount': str(item.discount),
                'total': str(item.total),
            }
            for item in self.order.items.select_related(
                'variant__product', 'variant__color', 'variant__size',
                'warehouse__assigned_user',
            )
        ]

# Create your models here.
