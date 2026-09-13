from django.db import migrations, models
from django.db.models import Count, Q, Sum


def _merge_accounts(
    CashAccount,
    PaymentTransaction,
    SalesRepCollection,
    schema_editor,
    account_ids,
):
    accounts = list(CashAccount.objects.filter(pk__in=account_ids).order_by('pk'))
    if len(accounts) < 2:
        return

    canonical = accounts[0]
    duplicate_ids = [account.pk for account in accounts[1:]]
    total_balance = CashAccount.objects.filter(pk__in=account_ids).aggregate(
        value=Sum('balance'),
    )['value'] or 0

    PaymentTransaction.objects.filter(cash_account_id__in=duplicate_ids).update(
        cash_account_id=canonical.pk,
    )
    SalesRepCollection.objects.filter(cash_account_id__in=duplicate_ids).update(
        cash_account_id=canonical.pk,
    )

    assigned_user_id = canonical.assigned_user_id
    if not assigned_user_id:
        assigned_user_id = next(
            (account.assigned_user_id for account in accounts if account.assigned_user_id),
            None,
        )
    CashAccount.objects.filter(pk=canonical.pk).update(
        balance=total_balance,
        is_active=any(account.is_active for account in accounts),
        allow_overdraft=any(account.allow_overdraft for account in accounts),
        assigned_user_id=assigned_user_id,
    )

    table = schema_editor.quote_name(CashAccount._meta.db_table)
    placeholders = ', '.join(['%s'] * len(duplicate_ids))
    schema_editor.execute(
        f'DELETE FROM {table} WHERE id IN ({placeholders})',
        duplicate_ids,
    )


def merge_duplicate_cash_accounts(apps, schema_editor):
    CashAccount = apps.get_model('finance', 'CashAccount')
    PaymentTransaction = apps.get_model('finance', 'PaymentTransaction')
    SalesRepCollection = apps.get_model('sales_reps', 'SalesRepCollection')

    duplicate_names = CashAccount.objects.values('branch_id', 'name').annotate(
        rows=Count('pk'),
    ).filter(rows__gt=1)
    for group in duplicate_names.iterator():
        account_ids = list(CashAccount.objects.filter(
            branch_id=group['branch_id'],
            name=group['name'],
        ).values_list('pk', flat=True))
        _merge_accounts(
            CashAccount,
            PaymentTransaction,
            SalesRepCollection,
            schema_editor,
            account_ids,
        )

    duplicate_rep_accounts = CashAccount.objects.filter(
        account_type='sales_rep_cash',
        assigned_user_id__isnull=False,
    ).values('branch_id', 'assigned_user_id').annotate(
        rows=Count('pk'),
    ).filter(rows__gt=1)
    for group in duplicate_rep_accounts.iterator():
        account_ids = list(CashAccount.objects.filter(
            branch_id=group['branch_id'],
            account_type='sales_rep_cash',
            assigned_user_id=group['assigned_user_id'],
        ).values_list('pk', flat=True))
        _merge_accounts(
            CashAccount,
            PaymentTransaction,
            SalesRepCollection,
            schema_editor,
            account_ids,
        )


class Migration(migrations.Migration):

    # PostgreSQL cannot ALTER this table while the data-merge DELETE/UPDATE
    # operations still have pending FK trigger events in the same transaction.
    # Commit the merge first, then add the uniqueness constraints.
    atomic = False

    dependencies = [
        ('finance', '0011_paymenttransaction_affects_customer_balance'),
        ('sales_reps', '0003_alter_salesrepcollection_managers_and_more'),
    ]

    operations = [
        migrations.RunPython(
            merge_duplicate_cash_accounts,
            migrations.RunPython.noop,
            atomic=True,
        ),
        migrations.AddConstraint(
            model_name='cashaccount',
            constraint=models.UniqueConstraint(
                fields=('branch', 'name'),
                name='finance_cashaccount_branch_name_uniq',
            ),
        ),
        migrations.AddConstraint(
            model_name='cashaccount',
            constraint=models.UniqueConstraint(
                condition=Q(
                    account_type='sales_rep_cash',
                    assigned_user__isnull=False,
                ),
                fields=('branch', 'assigned_user'),
                name='finance_cashaccount_branch_rep_uniq',
            ),
        ),
    ]
