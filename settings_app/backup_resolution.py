"""Resolve explicitly reviewed snapshot differences without splitting ledgers."""
from collections import defaultdict


STRICT = 'strict'
KEEP_CURRENT = 'keep_current'
USE_ARCHIVE = 'use_archive'
RESOLUTIONS = (
    (KEEP_CURRENT, 'الإبقاء على القيم الحالية في التعارضات'),
    (USE_ARCHIVE, 'اعتماد قيم النسخة في التعارضات الممكن تطبيقها'),
)

LEDGER_APPS = {'finance', 'inventory', 'orders', 'invoices', 'purchases', 'returns', 'sales_reps'}
LEDGER_MODELS = {'customers.customer'}  # Includes the opening balance.
WRITES = {'create', 'update', 'conflict'}


def _is_ledger(label):
    return label in LEDGER_MODELS or label.split('.')[0] in LEDGER_APPS


def _references(record, schema):
    for field, definition in schema[record['model']]['fields'].items():
        if definition[-1] and record['fields'][field]:
            yield record['fields'][field]
    for values in record['m2m'].values():
        yield from values
    for value in record.get('refs', {}).values():
        if isinstance(value, dict):
            yield from value.values()
        else:
            yield value


def resolve_actions(records, current, schema, actions, conflicts, history_only, resolution):
    """Return withheld actions and branches whose incoming snapshot is partial."""
    if resolution == STRICT:
        return {}, set()

    incoming = {record['uid']: record for record in records}
    dependents = defaultdict(list)
    ledger_write_branches = set()
    branch_writes = defaultdict(list)
    for record in records:
        uid, label, branch = record['uid'], record['model'], record['fields'].get('branch')
        if actions[uid] not in WRITES:
            continue
        for ref in _references(record, schema):
            dependents[ref].append(uid)
        if _is_ledger(label):
            ledger_write_branches.add(branch)
        if _is_ledger(label) or label in history_only:
            user = incoming.get(record['fields'].get('user'))
            history_branch = branch or (user and user['fields'].get('branch'))
            branch_writes[history_branch].append(uid)

    deferred, partial = {}, set()
    queue = []

    def mark_deferred(uid, reason):
        if uid not in deferred:
            deferred[uid] = reason
            actions[uid] = 'defer'
            queue.append(uid)

    blocked_branches = set()

    def hold_ledger(branch, reason):
        if branch not in blocked_branches:
            blocked_branches.add(branch)
            for uid in branch_writes[branch]:
                mark_deferred(uid, reason)

    if resolution == USE_ARCHIVE:
        # An archived balance excludes local-only movements. Replacing it
        # while those movements remain would leave an inconsistent ledger.
        local_only_branches = {r['fields'].get('branch') for r in current
                               if _is_ledger(r['model']) and r['uid'] not in incoming}
        for branch in ledger_write_branches & local_only_branches:
            hold_ledger(branch, 'توجد سجلات مالية أو مخزنية حالية خارج النسخة.')

    for conflict in conflicts:
        uid, label = conflict['uid'], conflict['model']
        branch = incoming[uid]['fields'].get('branch')
        if label == 'accounts.user':
            mark_deferred(uid, 'الحساب الحالي تابع لمعرض آخر.')
        elif resolution == KEEP_CURRENT:
            partial.add(branch)
            if _is_ledger(label):
                hold_ledger(branch, 'تؤجل السجلات المالية والمخزنية المرتبطة حفاظًا على الأرصدة الحالية.')
            else:
                actions[uid] = 'skip'
        elif uid not in deferred:
            actions[uid] = 'update'

    # Withhold any new or updated row that needs a withheld reference. A
    # skipped financial write also withholds the rest of that branch's ledger.
    for uid in queue:
        record = incoming[uid]
        branch = record['fields'].get('branch')
        partial.add(branch)
        if _is_ledger(record['model']):
            hold_ledger(branch, 'توجد علاقة لازمة يتعذر تطبيقها ضمن بيانات هذا المعرض.')
        for dependent in dependents[uid]:
            mark_deferred(dependent, 'يعتمد هذا السجل على سجل تعذر تطبيقه.')

    return deferred, partial
