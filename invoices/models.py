from django.db import models

from orders.models import Order
from config.branching import BranchOwnedModel


class Invoice(BranchOwnedModel):
    branch_relations = ('order',)
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='invoice')
    invoice_number = models.CharField(max_length=50, db_index=True)
    issued_at = models.DateTimeField(auto_now_add=True, db_index=True)
    printed_count = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.invoice_number

    class Meta:
        constraints = [models.UniqueConstraint(fields=['branch', 'invoice_number'], name='invoices_invoice_branch_number_unique')]

    def infer_branch_id(self):
        return self.order.branch_id if self.order_id else None

# Create your models here.
