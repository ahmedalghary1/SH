# PWA and offline synchronization

Install from a compatible browser over HTTPS. Sign in online first so the
service worker and an authorized data snapshot can be downloaded. On iOS, use
Safari's **Add to Home Screen**. A locally saved invoice is provisional until
the server accepts its synchronization.

## Identity and storage

- `identity.js` derives a scope from user, branch, role, and superuser status,
  such as `u4-b2-rsales-s0`. IndexedDB uses `sh-offline-db-<scope>`.
- Business stores include sales, customers, products, variants, stock, warehouses,
  cash accounts, movements, and the synchronization queue. A local record and
  its queue entry commit together.
- Private HTML is cached separately per scope, only when a successful response
  explicitly supplies matching `X-PWA-Scope` and `X-PWA-Cacheable: 1`.
  Login, admin, API, media, and exports are excluded.
- HTTP `Vary` headers are retained. Private cache reads ignore `Vary` only inside
  the verified identity's cache. Logout clears private HTML caches; pending work
  remains in its account-specific database.
- Browser synchronization supplies `X-PWA-Scope`. The server returns HTTP 409
  before processing a request from a stale account/branch scope.
- A full bootstrap replaces server snapshots only when the queue is empty, and preserves unsent local edits.
  Offline stock is an estimate; synchronization checks stock and permissions again.

The old shared `sh-offline-db` is preserved and is **not automatically replayed
or imported**: older queued records do not prove their owner and branch. Before
updating a device with old pending work, reconcile or export that queue using
the old installation and review it with the responsible manager. Do not clear
browser storage to fix an update or synchronization problem.

## Supported work

Existing handlers capture supported customer, new sales-document, product,
stock movement, payment, purchase, return-creation, and representative forms.
Normal permissions also apply to synchronization.

Existing invoice editing/deletion, financial transaction editing/deletion,
purchase order editing/discount/receipt, existing return approval/completion,
and product file imports require their normal online workflow. Unsupported
forms show a connection-required message. Not every reporting or administration
screen supports offline writes; login and server-generated exports need a connection.

## Queue and retry behavior

1. Supported forms check browser/server reachability before dispatching a
   business POST. If unreachable, they save locally with a UUID.
2. A lost response to an already dispatched POST is never converted into an
   automatic offline replay: that write may already have committed.
3. The navigation bar shows the pending count. The queue dialog displays type,
   time, ID, and error, and exports a JSON copy without CSRF/submission tokens.
4. Reconnection, focus, periodic retry, and manual sync refresh the session and
   CSRF token. Operations run oldest first; Web Locks prevents concurrent tabs
   where supported. Server idempotency also protects browsers without Web Locks.
5. Temporary errors back off up to five minutes. Permanent conflicts remain
   visible and block later operations that could depend on them. Manual retry
   preserves the original key and does not replay permanent conflicts.
6. The server claims the unique idempotency key before processing. Receipt and
   business effects commit atomically. Concurrent duplicates return the original
   result; changed payload, user, device, or branch under that key is rejected.
7. Successful operations leave the queue and refresh server data.
   `server_newer_ignored` keeps the server version authoritative: review the
   record if an expected edit was not applied.

Keep the app open to finish synchronization. Background Sync and installation
prompts vary by browser; online/focus/manual paths do not depend on them. Browser
storage can be cleared or evicted by the operating system; export important
pending work and synchronize regularly.

## Cache and releases

Assets are versioned together in `static/service-worker.js`. Navigation checks
the network first with an eight-second timeout. Cached pages can cover network
failure or HTTP 502/503/504; HTTP 403/500 remain visible. Up to 100 private URLs
are retained. Prefetch uses three workers and skips recently cached pages.

Updates wait for explicit activation. The update button checks unsaved forms
and pending operations. Publish a complete release, collect static files, and
restart the application together; changing served files in place under a
running process can invalidate its cached file metadata.

## API

- `GET /api/sync/session/`: authenticated scope and a fresh CSRF token.
- `GET /api/sync/bootstrap-browser/`: full authorized snapshot and scope.
- `GET /api/sync/changes-browser/?since=<ISO datetime>`: existing changes API.
- `POST /api/sync/{sales,customers,products,stock,cash,returns,driver-actions,purchases}/`:
  browser operations with session authentication and CSRF.
- Token clients retain `/api/sync/bootstrap/`, `/api/sync/changes/`, and
  `/api/sync/push/`. Push accepts at most 100 operations per request.

## Verification

`node --test tests/js/*.test.js` covers cache isolation, logout cleanup,
non-replay of dispatched POSTs, and visible permission/server errors.
`sync_api.tests_resilience` covers idempotency, branch/permission boundaries,
session scope, invalid input, and concurrent PostgreSQL requests. Use disposable
databases. Release results and production limits appear in the
[Arabic review report](review-2026-10-12-ar.md).


## Stock integrity improvements (2026-11-09)

- Confirmed offline sales commit the invoice, queue entry, and stock reservation
  in one IndexedDB transaction. Insufficient stock rejects the complete save.
  Duplicate variant/warehouse lines are aggregated. Read/write transactions also
  serialize simultaneous reservations from multiple tabs. Quotes and held drafts
  do not reserve stock, matching the server workflow.
- Bulk warehouse transfers support up to 100 lines, including repeated variants.
  Both warehouse effects commit locally together. The server groups repeated
  variants and applies the entire document atomically, preserving batch costs.
  A failed line rolls back all lines. Legacy single-item queue entries still work.
- Bootstrap and queue processing share the same Web Lock. Snapshot import checks
  the queue inside its IndexedDB transaction and defers while any item remains,
  including conflicts or deferred retries. This prevents a downloaded stock value
  from erasing local reservations, including after a lost server acknowledgement.
  An atomic queue revision also rejects downloads that became stale while another
  tab queued and synchronized work, including on browsers without Web Locks.
- Stock refresh runs on reconnect, focus and periodically while the app is open.
  The offline stock list reads local quantities rather than cached HTML quantities.
  Local invoice list totals now include item and invoice discounts.
- Existing queues and IndexedDB data are retained. Deploy the whole release and
  collect static files; the new service worker version includes the bulk form JS.

The browser test `tests/pwa_browser_review.py` uses an isolated SQLite database,
real Chromium IndexedDB, service worker caching, offline invoice form capture,
concurrent reservations, a deliberately lost acknowledgement, reconnection,
server idempotency, and bulk-transfer replay. Run it with a Python environment
containing Playwright and an installed Chromium browser:

```powershell
.venv-audit/Scripts/python.exe tests/pwa_browser_review.py
```

Offline quantities represent this device's last download plus its own queued
work. Other devices can consume stock while disconnected; the server remains
responsible for final validation. Conflicts remain visible for reconciliation.
A permanent conflict intentionally pauses dependent operations and snapshot
replacement. Keep the application open to complete retries; do not clear storage.


## Representative negative-stock sales (2026-11-09)

Representatives can create a single-variant product using
`/products/representative/create/` and sell active branch catalog items from their
own active representative warehouse, including zero or negative quantities.
Creation starts with zero stock. Prices and an optional estimated cost are
captured; existing products are selected by their existing code to avoid duplicates.
This permission does not allow representatives to edit existing products, create
purchase receipts, change another warehouse's stock, or make samples negative.
Managers and warehouse users retain ordinary availability checks when selling.

Offline product and variant records commit with their queue entry. Local variant
references are resolved on the server through the same user's/device's successful
product receipt before accepting dependent sales. An atomic queue sequence orders
operations even when timestamps tie or the device clock changes. Forms containing
local product references remain queued when connectivity returns mid-edit.

Receipts, transfers and returns into the same warehouse increase its signed
balance. Incoming batches first settle the negative quantity, leaving only the
surplus available for future FIFO sales. For example, -10 + 6 = -4 and a further
10 received leaves +6, with exactly six units available in batches. Purchasing
into the main warehouse requires the usual transfer to the representative's
warehouse to settle that custody balance.

A shortage uses the variant's current cost as a provisional sale cost. Later
purchase receipts set the cost of newly received batches; they do not retroactively
rewrite the original invoice's profit. Set the estimated product cost if known.

This release includes inventory migration 0014 to permit signed stock balances.
Deploy with `python manage.py migrate`, collect static files and restart the app;
then update the PWA and download the authorized snapshot online before departure.
Existing queues are retained. PostgreSQL concurrency tests require PostgreSQL.
