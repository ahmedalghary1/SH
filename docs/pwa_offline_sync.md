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
- A full bootstrap replaces server snapshots and preserves unsent local edits.
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
