import json
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from config.branching import reset_current_branch, set_current_branch
from customers.models import Customer
from finance.reconciliation import (
    apply_customer_return_review,
    build_customer_return_review,
)


class Command(BaseCommand):
    help = 'Review legacy return balances; apply only explicitly selected, verified invoice repairs.'

    def add_arguments(self, parser):
        parser.add_argument('--customer', type=int, required=True)
        parser.add_argument('--order', type=int, action='append', dest='order_ids')
        parser.add_argument('--output', help='Save a read-only review report to a new JSON file.')
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--report', help='Previously reviewed JSON report; required with --apply.')
        parser.add_argument('--actor', help='Active manager username; required with --apply.')

    def handle(self, *args, **options):
        try:
            customer = Customer.all_objects.get(pk=options['customer'])
        except Customer.DoesNotExist as exc:
            raise CommandError('Customer does not exist.') from exc
        token = set_current_branch(customer.branch_id)
        try:
            if options['apply']:
                repaired = self.apply_report(customer, options)
                self.stdout.write(self.style.SUCCESS(
                    f'Repaired {repaired} invoice(s). Cash, stock and opening balance were not changed.',
                ))
            else:
                self.review(customer, options)
        finally:
            reset_current_branch(token)

    def review(self, customer, options):
        report = build_customer_return_review(customer, options['order_ids'])
        rows = report['orders']
        self.stdout.write('REVIEW ONLY: no database changes.\nOrder | stored | expected | result')
        for row in rows:
            result = 'BLOCKED: ' + ', '.join(row['problems']) if row['problems'] else (
                'REPAIR AVAILABLE' if row['needs_repair'] else 'OK')
            self.stdout.write(f"{row['order_id']} | {row['remaining_before']} | {row['remaining_expected']} | {result}")
        self.stdout.write(f"Customer balance: {report['balance_before']}; after verified repairs: {report['balance_after_verified_repairs']}")
        if options['output']:
            try:
                with Path(options['output']).open('x', encoding='utf-8') as output:
                    json.dump(report, output, ensure_ascii=False, indent=2)
            except OSError as exc:
                raise CommandError(f'Cannot create report: {exc}') from exc
            self.stdout.write(f"Report saved: {options['output']}")

    def apply_report(self, customer, options):
        if not options['report'] or not options['actor'] or not options['order_ids']:
            raise CommandError('--apply requires --report, --actor and at least one --order.')
        try:
            report = json.loads(Path(options['report']).read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise CommandError(f'Cannot read report: {exc}') from exc
        actor = User.objects.filter(username=options['actor'], is_active=True).first()
        try:
            return apply_customer_return_review(customer=customer, actor=actor, report=report, order_ids=options['order_ids'])
        except ValidationError as exc:
            raise CommandError('; '.join(exc.messages)) from exc
