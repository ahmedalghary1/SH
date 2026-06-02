from django.db import models

from orders.models import Order


class Invoice(models.Model):
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='invoice')
    invoice_number = models.CharField(max_length=50, unique=True, db_index=True)
    issued_at = models.DateTimeField(auto_now_add=True, db_index=True)
    printed_count = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.invoice_number

# Create your models here.
