CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  server_id INTEGER,
  username TEXT NOT NULL UNIQUE,
  full_name TEXT,
  role TEXT,
  permissions_json TEXT,
  token_encrypted TEXT,
  last_login_at TEXT,
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS products (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  server_id INTEGER UNIQUE,
  name TEXT NOT NULL,
  sku TEXT,
  category TEXT,
  is_active INTEGER DEFAULT 1,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS product_variants (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  server_id INTEGER UNIQUE,
  product_server_id INTEGER,
  local_product_id INTEGER,
  color TEXT,
  size TEXT,
  variant_sku TEXT,
  barcode TEXT,
  sale_price REAL DEFAULT 0,
  cost_price REAL DEFAULT 0,
  image_path TEXT,
  is_active INTEGER DEFAULT 1,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS local_stock (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  variant_server_id INTEGER,
  local_variant_id INTEGER,
  warehouse_server_id INTEGER,
  warehouse_name TEXT,
  quantity REAL DEFAULT 0,
  min_quantity REAL DEFAULT 0,
  updated_at TEXT,
  UNIQUE(variant_server_id, warehouse_server_id)
);

CREATE TABLE IF NOT EXISTS customers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  server_id INTEGER,
  local_uuid TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  phone TEXT,
  whatsapp TEXT,
  customer_type TEXT,
  address TEXT,
  credit_limit REAL DEFAULT 0,
  opening_balance REAL DEFAULT 0,
  is_synced INTEGER DEFAULT 0,
  sync_status TEXT DEFAULT 'synced',
  sync_error TEXT,
  updated_at TEXT,
  deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  server_id INTEGER,
  local_uuid TEXT UNIQUE NOT NULL,
  order_number_local TEXT,
  customer_server_id INTEGER,
  customer_local_uuid TEXT,
  document_type TEXT,
  order_type TEXT,
  status TEXT,
  payment_status TEXT,
  payment_method TEXT,
  subtotal REAL DEFAULT 0,
  discount REAL DEFAULT 0,
  total REAL DEFAULT 0,
  paid_amount REAL DEFAULT 0,
  remaining_amount REAL DEFAULT 0,
  notes TEXT,
  created_by_server_id INTEGER,
  created_by_name TEXT,
  sync_status TEXT DEFAULT 'pending',
  sync_error TEXT,
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS order_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_local_uuid TEXT NOT NULL,
  variant_server_id INTEGER,
  local_variant_id INTEGER,
  quantity REAL NOT NULL,
  unit_price REAL NOT NULL,
  discount REAL DEFAULT 0,
  total REAL NOT NULL,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS payment_transactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  server_id INTEGER,
  local_uuid TEXT UNIQUE NOT NULL,
  transaction_type TEXT,
  direction TEXT,
  amount REAL NOT NULL,
  customer_server_id INTEGER,
  customer_local_uuid TEXT,
  order_server_id INTEGER,
  order_local_uuid TEXT,
  payment_method TEXT,
  notes TEXT,
  sync_status TEXT DEFAULT 'pending',
  sync_error TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS returns (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  server_id INTEGER,
  local_uuid TEXT UNIQUE NOT NULL,
  order_server_id INTEGER,
  order_local_uuid TEXT,
  return_type TEXT,
  status TEXT,
  reason TEXT,
  refund_amount REAL DEFAULT 0,
  sync_status TEXT DEFAULT 'pending',
  sync_error TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS sync_queue (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  idempotency_key TEXT UNIQUE NOT NULL,
  entity_type TEXT NOT NULL,
  entity_local_uuid TEXT NOT NULL,
  operation_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  status TEXT DEFAULT 'pending',
  retry_count INTEGER DEFAULT 0,
  error_message TEXT,
  created_at TEXT,
  last_attempt_at TEXT,
  synced_at TEXT
);

CREATE TABLE IF NOT EXISTS sync_meta (
  key TEXT PRIMARY KEY,
  value TEXT
);

CREATE TABLE IF NOT EXISTS app_settings (
  key TEXT PRIMARY KEY,
  value TEXT
);

CREATE INDEX IF NOT EXISTS idx_sync_queue_status ON sync_queue(status, created_at);
CREATE INDEX IF NOT EXISTS idx_orders_sync_status ON orders(sync_status, created_at);
CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone);
CREATE INDEX IF NOT EXISTS idx_variants_lookup ON product_variants(variant_sku, barcode);
