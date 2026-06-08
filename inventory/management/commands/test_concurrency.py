import time
from threading import Thread
from django.core.management.base import BaseCommand
from django.db import connections
from django.core.exceptions import ValidationError
from inventory.services import stock_in, stock_out
from inventory.models import Stock, Warehouse
from products.models import Product, ProductVariant, Color, Size
from accounts.models import User


class Command(BaseCommand):
    help = "Simulates concurrent stock checkout (2 requests trying to deduct 5 units from stock of 7)"

    def handle(self, *args, **options):
        self.stdout.write("Setting up test data...")
        # Create user
        user, _ = User.objects.get_or_create(username="concurrency_test_user", defaults={"role": User.ROLE_MANAGER})
        user.set_password("pass123")
        user.save()

        # Create warehouse and products
        warehouse, _ = Warehouse.objects.get_or_create(name="Concurrency Warehouse", defaults={"warehouse_type": Warehouse.TYPE_MAIN})
        color, _ = Color.objects.get_or_create(name="ConcurrencyColor")
        size, _ = Size.objects.get_or_create(name="ConcurrencySize")
        product, _ = Product.objects.get_or_create(name="Concurrency Product", defaults={"sku": "CONC001"})
        variant, _ = ProductVariant.objects.get_or_create(
            product=product,
            color=color,
            size=size,
            defaults={"variant_sku": "CONC001-COL-SIZ", "cost_price": 10, "sale_price": 20}
        )

        # Clear existing stock
        Stock.objects.filter(warehouse=warehouse, variant=variant).delete()
        from inventory.models import StockBatch, StockMovement
        StockBatch.objects.filter(warehouse=warehouse, variant=variant).delete()
        StockMovement.objects.filter(variant=variant).delete()

        # Stock in 7 units
        stock_in(variant=variant, warehouse=warehouse, quantity=7, user=user, source="initial")
        
        stock = Stock.objects.get(warehouse=warehouse, variant=variant)
        self.stdout.write(self.style.SUCCESS(f"Initial stock: {stock.quantity}"))

        results = []

        def worker(thread_name, delay):
            # Close connection to force thread to create its own connection
            connections.close_all()
            try:
                # Add delay to coordinate starting times
                time.sleep(delay)
                self.stdout.write(f"[{thread_name}] Attempting to deduct 5 units...")
                stock_out(variant=variant, warehouse=warehouse, quantity=5, user=user, note=f"Deduction by {thread_name}")
                results.append((thread_name, True, "Success"))
                self.stdout.write(self.style.SUCCESS(f"[{thread_name}] Deducted 5 units successfully!"))
            except ValidationError as e:
                msg = getattr(e, 'message', None) or str(e)
                results.append((thread_name, False, f"ValidationError: {msg}"))
                try:
                    self.stdout.write(self.style.WARNING(f"[{thread_name}] Failed: {msg}"))
                except UnicodeEncodeError:
                    self.stdout.write(self.style.WARNING(f"[{thread_name}] Failed (Validation Error, Arabic characters omitted for encoding compatibility)"))
            except Exception as e:
                results.append((thread_name, False, f"Error: {str(e)}"))
                try:
                    self.stdout.write(self.style.ERROR(f"[{thread_name}] Error: {str(e)}"))
                except UnicodeEncodeError:
                    self.stdout.write(self.style.ERROR(f"[{thread_name}] Error (Unicode details omitted)"))
            finally:
                connections.close_all()

        # Spawn threads
        t1 = Thread(target=worker, args=("Thread-1", 0.1))
        t2 = Thread(target=worker, args=("Thread-2", 0.12)) # slightly delayed so they run concurrently

        t1.start()
        t2.start()

        t1.join()
        t2.join()

        # Fetch final stock
        stock.refresh_from_db()
        self.stdout.write(self.style.SUCCESS(f"Final stock quantity: {stock.quantity}"))

        success_count = sum(1 for r in results if r[1])
        self.stdout.write(f"Successful operations: {success_count}/2")

        # Cleanup
        Stock.objects.filter(warehouse=warehouse, variant=variant).delete()
        StockBatch.objects.filter(warehouse=warehouse, variant=variant).delete()
        StockMovement.objects.filter(variant=variant).delete()

        if stock.quantity < 0:
            self.stdout.write(self.style.ERROR("CRITICAL FAILURE: Stock quantity became negative!"))
        elif success_count == 1 and stock.quantity == 2:
            self.stdout.write(self.style.SUCCESS("CONCURRENCY TEST PASSED: Only 1 operation succeeded, stock is safe."))
        else:
            self.stdout.write(self.style.WARNING("Concurrency test completed, but check results above (SQLite may serialize operations resulting in 1 success, which is safe)."))
