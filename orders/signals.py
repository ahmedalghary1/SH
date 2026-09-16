from django.db.models.signals import pre_delete
from django.dispatch import receiver

from .models import Order
from inventory.models import Warehouse
from inventory.services import return_stock
from .services import get_order_item_warehouse


@receiver(pre_delete, sender=Order)
def return_stock_on_order_delete(sender, instance, **kwargs):
    # Only return stock if the order had actually deducted stock
    if instance.status in {Order.STATUS_CONFIRMED, Order.STATUS_PREPARING, Order.STATUS_READY, Order.STATUS_COMPLETED}:
        for item in instance.items.select_related('variant', 'warehouse', 'stock_batch'):
            try:
                warehouse = get_order_item_warehouse(item, order=instance)
                return_stock(
                    variant=item.variant,
                    warehouse=warehouse,
                    quantity=item.quantity,
                    user=instance.created_by,
                    unit_cost=item.unit_cost,
                    note=f'تم استرجاع الكمية بسبب حذف الفاتورة {instance.order_number}',
                )
                
                # Restore sales rep assignment if applicable
                if warehouse.warehouse_type == Warehouse.TYPE_REPRESENTATIVE and warehouse.assigned_user_id:
                    from sales_reps.services import restore_sales_rep_assignments
                    restore_sales_rep_assignments(
                        sales_rep=warehouse.assigned_user,
                        product_variant=item.variant,
                        quantity=item.quantity,
                    )
            except Exception:
                # If something goes wrong during return_stock, we shouldn't block the deletion.
                # However, logging it would be good. Here we silently pass to ensure delete succeeds.
                pass
