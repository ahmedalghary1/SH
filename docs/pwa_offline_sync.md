# PWA Offline Sync Integration

## Structure

- `static/manifest.json` - installable PWA manifest.
- `static/service-worker.js` - root-scoped offline cache worker, served by `config.pwa.service_worker_view`.
- `templates/offline.html` - navigation fallback when a cached page is unavailable offline.
- `static/icons/icon-192.png` and `static/icons/icon-512.png` - manifest icons.
- `static/js/pwa/db.js` - IndexedDB wrapper and local stores.
- `static/js/pwa/sync-queue.js` - queue exports for offline operations.
- `static/js/pwa/sync-engine.js` - automatic bootstrap, queue processing, retries, and online detection.
- `static/js/pwa/offline-forms.js` - offline form capture and local AJAX fallbacks.
- `sync_api/views.py` and `sync_api/services.py` - browser sync endpoints and conflict-safe processors.

## Local Stores

IndexedDB database: `sh-offline-db`

Stores:

- `sales`
- `customers`
- `products`
- `product_variants`
- `stock`
- `stock_movements`
- `cash_transactions`
- `driver_actions`
- `sync_queue`
- `metadata`

Each locally written business record includes:

- `id`
- `local_uuid`
- `created_at`
- `updated_at`
- `sync_status`
- `operation_type`

Queue rows include:

- `action_type`
- `entity_name`
- `entity_type`
- `payload`
- `timestamp`
- `status`
- `attempts`
- `next_attempt_at`
- `idempotency_key`

## Browser API Endpoints

- `GET /api/sync/bootstrap-browser/`
- `GET /api/sync/changes-browser/?since=<iso datetime>`
- `POST /api/sync/sales/`
- `POST /api/sync/products/`
- `POST /api/sync/stock/`
- `POST /api/sync/customers/`
- `POST /api/sync/cash/`
- `POST /api/sync/returns/`
- `POST /api/sync/driver-actions/`

The existing token endpoints remain available for non-browser clients:

- `GET /api/sync/bootstrap/`
- `GET /api/sync/changes/`
- `POST /api/sync/push/`

## Example Flow

1. User opens the app online.
2. `main.js` registers `/service-worker.js`.
3. The top bar shows an install button when the browser exposes the PWA install prompt.
4. `sync-engine.js` downloads `/api/sync/bootstrap-browser/` and caches all permitted products, variants, stock, customers, orders, warehouses, and cash accounts in IndexedDB.
5. Cached data is scoped by the logged-in user's existing Django permissions:
   managers/directors see all business data, sales users see their allowed stock/customers/orders, and warehouse users see inventory/warehouse-visible data.
6. User loses internet and creates an invoice.
7. `offline-forms.js` prevents the failing POST, writes the invoice to `sales`, decrements cached stock, and inserts a `sync_queue` row.
8. Internet returns.
9. `sync-engine.js` processes `sync_queue` oldest first and POSTs the invoice operation to `/api/sync/sales/`.
10. Django validates the payload with the same order service used by the website, applies idempotency, compares timestamps, and writes the invoice.
11. The queue row is removed and the local invoice is marked `synced`.
12. A fresh bootstrap refreshes local server IDs and stock.

## Conflict Rules

- Server record newer than local `updated_at`: local operation is ignored and returns `resolution=server_newer_ignored`.
- Local record newer: server is updated and returns `resolution=local_applied`.
- Server record missing for an update/delete: local record is treated as remotely deleted and returns `resolution=server_deleted`.
- Duplicate idempotency key with the same payload returns the original result.
- Duplicate idempotency key with a different payload returns `failed_conflict`.
- Transient `failed` operations can retry with the same idempotency key.
