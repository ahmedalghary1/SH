"""Read-only business reconciliation; never silently repairs historical money."""
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection
from django.db.models import F, Sum


class Command(BaseCommand):
    help = 'Inspect business balances and relationship integrity without changing records.'

    def add_arguments(self, parser):
        parser.add_argument('--output', help='Write an audit JSON report to this path.')

    def handle(self, **options):
        from django.apps import apps
        from config.branching import BranchOwnedModel
        from customers.models import Customer
        from customers.services import annotate_customer_balances, get_customer_summary
        from finance.models import CashAccount, PaymentTransaction
        from finance.reconciliation import inspect_order_return_balance
        from finance.services import build_customer_statement
        from inventory.models import Stock, StockBatch, Warehouse
        from orders.models import Order
        from purchases.models import PurchaseOrder, Supplier

        findings = defaultdict(lambda: {'count': 0, 'examples': []})
        checked = defaultdict(int)

        def finding(code, pk, **data):
            item = findings[code]
            item['count'] += 1
            if len(item['examples']) < 50:
                item['examples'].append({'id': pk, **data})

        # A read-only transaction also guards this command against accidental writes.
        from django.db import transaction
        outer_transaction = connection.in_atomic_block
        with transaction.atomic():
            if connection.vendor == 'postgresql' and not outer_transaction:
                with connection.cursor() as cursor:
                    cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            elif connection.vendor == 'sqlite':
                with connection.cursor() as cursor:
                    cursor.execute('PRAGMA query_only = ON')
            try:
                for model in apps.get_models():
                    if not issubclass(model, BranchOwnedModel):
                        continue
                    for relation in model.branch_relations:
                        for pk in model.all_objects.filter(**{f'{relation}__isnull': False}).exclude(
                                branch_id=F(f'{relation}__branch_id')).values_list('pk', flat=True):
                            finding('cross_branch_relation', pk, model=model._meta.label, relation=relation)

                for order in Order.all_objects.filter(document_type=Order.DOCUMENT_SALE).exclude(
                        status__in=[Order.STATUS_DRAFT, Order.STATUS_CANCELLED]).prefetch_related('items'):
                    checked['orders'] += 1
                    line_total = sum((row.total for row in order.items.all()), Decimal(0))
                    line_cost = sum((row.cost_total for row in order.items.all()), Decimal(0))
                    if line_total - order.discount != order.total:
                        finding('order_total_mismatch', order.pk, stored=order.total, expected=line_total - order.discount)
                    if line_cost != order.total_cost or order.gross_profit != order.total - order.total_cost:
                        finding('order_cost_or_profit_mismatch', order.pk)
                    state = inspect_order_return_balance(order)
                    if state['needs_repair'] or state['problems']:
                        finding('order_payment_or_return_mismatch', order.pk, problems=state['problems'],
                                stored=order.remaining_amount, expected=state['remaining_expected'])

                for customer in annotate_customer_balances(Customer.all_objects.all()):
                    checked['customers'] += 1
                    statement = build_customer_statement(customer)['current_balance']
                    summary = get_customer_summary(customer)['total_remaining']
                    if statement != summary or statement != customer.current_balance:
                        finding('customer_balance_views_disagree', customer.pk, statement=statement,
                                summary=summary, annotated=customer.current_balance)

                for purchase in PurchaseOrder.all_objects.exclude(status__in=['draft', 'cancelled']).prefetch_related('items'):
                    checked['purchases'] += 1
                    base = sum((row.unit_cost * row.quantity for row in purchase.items.all()), Decimal(0))
                    expected = (base - purchase.discount_amount).quantize(Decimal('0.01'))
                    if (purchase.total_amount != expected or purchase.paid_amount > expected
                            or purchase.remaining_amount != expected - purchase.paid_amount):
                        finding('purchase_total_or_payment_mismatch', purchase.pk, total=purchase.total_amount,
                                paid=purchase.paid_amount, remaining=purchase.remaining_amount)
                    for row in purchase.items.all():
                        if row.received_quantity > row.quantity:
                            finding('purchase_over_received', row.pk)

                for supplier in Supplier.all_objects.all():
                    checked['suppliers'] += 1
                    purchases = supplier.purchase_orders.exclude(status__in=['draft', 'cancelled']).aggregate(v=Sum('total_amount'))['v'] or Decimal(0)
                    credits = PaymentTransaction.all_objects.filter(related_supplier=supplier,
                        transaction_type__in=[PaymentTransaction.TYPE_SUPPLIER_PAYMENT, PaymentTransaction.TYPE_SUPPLIER_RETURN]).aggregate(v=Sum('amount'))['v'] or Decimal(0)
                    expected = supplier.opening_balance + purchases - credits
                    if supplier.current_balance != expected:
                        finding('supplier_balance_requires_review', supplier.pk, stored=supplier.current_balance,
                                reconstructed=expected)

                for stock in Stock.all_objects.select_related('warehouse'):
                    checked['stock_positions'] += 1
                    if stock.quantity < 0 and stock.warehouse.warehouse_type != Warehouse.TYPE_REPRESENTATIVE:
                        finding('negative_non_representative_stock', stock.pk)
                    available = StockBatch.all_objects.filter(variant_id=stock.variant_id,
                        warehouse_id=stock.warehouse_id).aggregate(v=Sum('remaining_quantity'))['v'] or 0
                    if available != max(stock.quantity, 0):
                        finding('stock_batch_balance_requires_review', stock.pk, quantity=stock.quantity, batches=available)
                for batch in StockBatch.all_objects.filter(remaining_quantity__gt=F('received_quantity')):
                    finding('batch_over_received', batch.pk)
                for account in CashAccount.all_objects.filter(balance__lt=0, allow_overdraft=False):
                    finding('cash_overdraft_without_permission', account.pk)
            finally:
                if connection.vendor == 'sqlite':
                    with connection.cursor() as cursor:
                        cursor.execute('PRAGMA query_only = OFF')

        report = {'read_only': True, 'database_vendor': connection.vendor, 'checked': dict(checked),
            'findings': dict(findings), 'finding_count': sum(row['count'] for row in findings.values()),
            'limitations': ['Legacy opening stock and cash balances lack independent immutable opening snapshots.',
                'Legacy supplier returns/raw purchases without separate ledger records need document review.',
                'No historical financial record is repaired automatically.']}
        rendered = json.dumps(report, cls=DjangoJSONEncoder, ensure_ascii=False, indent=2)
        if options['output']:
            Path(options['output']).write_text(rendered + '\n', encoding='utf-8')
        self.stdout.write(json.dumps({'checked': report['checked'], 'finding_count': report['finding_count'],
                                     'by_code': {key: value['count'] for key, value in findings.items()}}))
