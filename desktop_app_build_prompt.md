# برومت احترافي لبناء تطبيق Desktop داخل مشروع Django ERP الحالي

## الهدف
أريد بناء تطبيق Desktop عربي كامل داخل **نفس مسار المشروع الحالي** دون كسر أو تعديل الموقع الرئيسي بشكل عشوائي.
المشروع الحالي عبارة عن موقع Django ERP لإدارة الملابس، وأريد إنشاء نسخة Desktop مرتبطة به تعمل Online و Offline، ويتم إنشاؤها داخل مجلد جديد باسم:

```txt
desktop_app
```

يجب أن يتم إنشاء هذا المجلد داخل المسار الحالي للمشروع، بجانب ملفات وتطبيقات Django الحالية، وليس داخل أي app من تطبيقات Django.

---

## التعليمات الأساسية قبل كتابة أي كود
قبل إنشاء أي ملفات جديدة، يجب تحليل المشروع الحالي جيدًا، ويجب عدم افتراض أسماء التطبيقات أو الموديلات أو المسارات بدون فحص فعلي.

ابدأ بالخطوات التالية:

1. افحص هيكل المشروع الحالي بالكامل.
2. حدد ملف إعدادات Django المستخدم فعليًا.
3. حدد أسماء تطبيقات المشروع الحالية مثل:
   - accounts
   - products
   - inventory
   - customers
   - orders
   - finance
   - returns
   - purchases
   - sales_reps
   - audit
   - reports
   - dashboard
   - settings_app
4. افحص الموديلات الحالية المرتبطة بـ:
   - المستخدمين والصلاحيات
   - المنتجات والمتغيرات
   - المخزون والعهد
   - العملاء
   - فواتير البيع
   - التحصيلات
   - المرتجعات والاستبدال
   - سجل التدقيق
5. افحص نظام الصلاحيات الحالي وكيف يتم تحديد أدوار المستخدمين.
6. افحص تصميم الواجهة الحالي من ملفات templates و static حتى يكون تطبيق الديسكتوب مشابهًا له بصريًا.
7. افحص إن كانت هناك APIs موجودة بالفعل قبل إنشاء APIs جديدة.
8. لا تكرر منطق موجود بالفعل، بل استخدمه أو ابنِ عليه بطريقة منظمة.

ممنوع البدء في بناء التطبيق قبل الانتهاء من تحليل المشروع الحالي.

---

## النتيجة المطلوبة
إنشاء تطبيق Desktop احترافي باسم `desktop_app` يعمل باستخدام:

- Electron كتغليف Desktop.
- HTML / CSS / JavaScript للواجهة.
- SQLite كقاعدة بيانات محلية Offline.
- REST API أو JSON Sync للربط مع Django ERP الحالي.
- Offline-first workflow.
- Sync Queue لمنع فقدان العمليات.
- واجهة عربية بالكامل RTL.
- تصميم قريب جدًا من لوحة ERP الحالية وليس Landing Page.

التطبيق يجب أن يكون مناسبًا للمندوبين وموظفي المخزن والمبيعات، بحيث يستطيع المستخدم العمل بدون إنترنت، ثم تتم مزامنة البيانات عند عودة الاتصال.

---

## مكان إنشاء التطبيق
أنشئ مجلد جديد في المسار الحالي للمشروع باسم:

```txt
desktop_app/
```

ويكون الهيكل العام كالتالي:

```txt
desktop_app/
  package.json
  README.md
  .env.example
  electron/
    main.js
    preload.js
    ipc/
      auth.ipc.js
      db.ipc.js
      sync.ipc.js
      settings.ipc.js
  src/
    renderer/
      index.html
      css/
        main.css
        layout.css
        components.css
        rtl.css
      js/
        app.js
        router.js
        config.js
        apiClient.js
        auth.js
        db.js
        syncService.js
        networkService.js
        notifications.js
        repositories/
          usersRepo.js
          productsRepo.js
          stockRepo.js
          customersRepo.js
          ordersRepo.js
          paymentsRepo.js
          returnsRepo.js
          syncQueueRepo.js
          syncMetaRepo.js
        screens/
          login.js
          dashboard.js
          products.js
          customers.js
          orderCreate.js
          payments.js
          returns.js
          syncLog.js
          settings.js
  database/
    schema.sql
    migrations/
      001_initial.sql
  assets/
    icons/
    fonts/
  logs/
  docs/
    sync-flow.md
    api-contract.md
    offline-rules.md
    testing-scenarios.md
```

لا تستخدم اسم `desktop-app` بشرطة، بل استخدم الاسم المطلوب بالضبط:

```txt
desktop_app
```

---

## قواعد مهمة جدًا لحماية المشروع الحالي
1. لا تعدل ملفات الموقع الرئيسي إلا عند الحاجة الضرورية لإضافة API endpoints أو إعدادات sync.
2. أي تعديل في Django يجب أن يكون واضحًا ومحدودًا.
3. لا تكسر صفحات الموقع الحالية.
4. لا تغير أسماء الموديلات الحالية بدون سبب.
5. لا تغير منطق المبيعات أو المخزون الحالي إلا إذا كان ذلك مطلوبًا للـ sync وبشكل آمن.
6. لا تنشئ نظام ERP جديد من الصفر منفصل عن المشروع الحالي.
7. تطبيق الديسكتوب يجب أن يكون عميلًا مرتبطًا بالمشروع الحالي.
8. أي كود جديد في Django خاص بالمزامنة يجب وضعه في app واضح مثل:

```txt
sync_api/
```

إذا لم يكن موجودًا بالفعل.

---

## تحليل المشروع الحالي المطلوب قبل التنفيذ
أنشئ تقريرًا داخليًا أو ملفًا باسم:

```txt
desktop_app/docs/project-analysis.md
```

يحتوي على:

1. هيكل المشروع الحالي.
2. التطبيقات الموجودة.
3. الموديلات المهمة التي سيتم الربط معها.
4. صفحات الواجهة التي سيتم تقليد تصميمها.
5. ملفات CSS الأساسية المستخدمة في الموقع.
6. نظام تسجيل الدخول الحالي.
7. نظام الصلاحيات الحالي.
8. طريقة إدارة المنتجات والمتغيرات.
9. طريقة إدارة المخزون والعهد.
10. طريقة إنشاء الفواتير.
11. طريقة التحصيلات.
12. طريقة المرتجعات.
13. APIs الموجودة إن وجدت.
14. APIs الناقصة المطلوب إنشاؤها.
15. مخاطر التنفيذ ونقاط الحذر.

---

## وصف تطبيق الديسكتوب المطلوب
التطبيق نسخة Desktop مرتبطة بنظام ERP الحالي لإدارة الملابس.
يجب أن يعمل بطريقتين:

### Online Mode
عند وجود إنترنت:
- تسجيل الدخول من السيرفر.
- تحميل البيانات الأساسية من السيرفر.
- رفع العمليات فورًا للسيرفر.
- تحديث البيانات المحلية من السيرفر.

### Offline Mode
عند عدم وجود إنترنت:
- يسمح بالدخول فقط إذا كان المستخدم سبق له تسجيل الدخول بنجاح.
- يستخدم بيانات محفوظة محليًا.
- يسمح بإنشاء عمليات محلية حسب الصلاحيات.
- يحفظ العمليات في SQLite.
- يضع العمليات في Sync Queue.
- يعرض للمستخدم أن العملية محفوظة محليًا بانتظار المزامنة.

---

## السيناريو الأساسي
مندوب استلم كمية من المخزن وخرج للبيع في منطقة لا يوجد بها إنترنت.
يجب أن يستطيع من التطبيق:

1. تسجيل الدخول مسبقًا Online.
2. فتح التطبيق لاحقًا Offline.
3. عرض المنتجات الموجودة في عهدته.
4. إنشاء فواتير بيع.
5. إضافة عملاء جدد.
6. تسجيل تحصيلات من العملاء.
7. تسجيل مرتجعات أو استبدال إذا كانت صلاحياته تسمح بذلك.
8. حفظ كل العمليات محليًا.
9. عند عودة الاتصال:
   - رفع العمليات الجديدة للسيرفر.
   - تحديث حالة العمليات المحلية إلى Synced.
   - جلب أحدث المنتجات والمخزون والعملاء والفواتير من السيرفر.
   - التعامل مع التعارضات بدون حذف أي عملية محلية.

---

## واجهة المستخدم المطلوبة
التطبيق يجب أن يكون عربي بالكامل:

- اتجاه RTL.
- خط Cairo.
- شريط جانبي يمين.
- شريط علوي أزرق أو داكن حسب تصميم الموقع الحالي.
- خلفية رمادي فاتح.
- كروت بيضاء.
- أزرار واضحة.
- مناسب لشاشة لابتوب صغيرة.
- عملي وكثيف ومنظم.
- لا يستخدم تصميم Landing Page.
- يفتح مباشرة على شاشة Login أو Dashboard.

### ألوان مقترحة
استخدم هذه الألوان كأساس، مع محاولة مطابقتها مع ألوان الموقع الحالي بعد التحليل:

```css
:root {
  --primary-color: #0f172a;
  --secondary-color: #1e293b;
  --accent-color: #3b82f6;
  --accent-strong: #2563eb;
  --background-color: #f8fafc;
  --surface-color: #ffffff;
  --border-color: #e2e8f0;
  --text-color: #1e293b;
  --muted-text: #64748b;
  --success-color: #10b981;
  --warning-color: #f59e0b;
  --danger-color: #ef4444;
  --info-color: #0ea5e9;
}
```

---

## الشاشات المطلوبة

### 1. شاشة تسجيل الدخول
تحتوي على:
- اسم المستخدم.
- كلمة المرور.
- زر دخول.
- مؤشر حالة الاتصال Online / Offline.
- رسالة خطأ واضحة.
- Loading state أثناء تسجيل الدخول.

القواعد:
- إذا كان Online يتم التحقق من السيرفر.
- إذا كان Offline يسمح بالدخول فقط إذا كان المستخدم سبق له تسجيل الدخول بنجاح وتم حفظ token أو session محليًا بشكل آمن.
- لا تخزن كلمة المرور نصًا صريحًا.

---

### 2. لوحة التحكم الرئيسية
تعرض:
- حالة الاتصال.
- آخر مزامنة.
- عدد العمليات غير المتزامنة.
- مبيعات اليوم.
- عدد فواتير اليوم.
- إجمالي التحصيلات.
- المخزون المتاح للمستخدم أو المندوب.
- تنبيهات التعارض أو فشل المزامنة.
- أزرار سريعة:
  - فاتورة جديدة.
  - عميل جديد.
  - تحصيل جديد.
  - مزامنة الآن.

---

### 3. شاشة المنتجات / العهدة
تعرض المنتجات المتاحة للمستخدم حسب صلاحياته أو عهدته:

- اسم المنتج.
- اللون.
- المقاس.
- SKU.
- Barcode.
- الكمية المحلية.
- السعر.
- حالة المنتج.
- بحث بالاسم أو SKU أو Barcode.
- فلترة حسب التصنيف أو التوفر.

يجب أن تعمل الشاشة بالكامل بدون إنترنت.

---

### 4. شاشة إنشاء فاتورة بيع
تحتوي على:

- اختيار العميل.
- إنشاء عميل سريع من نفس الشاشة.
- البحث عن المنتج بالباركود أو SKU أو الاسم.
- اختيار الكمية.
- عرض السعر.
- حساب الإجمالي.
- الخصم إذا كان مسموحًا.
- المدفوع.
- المتبقي.
- طريقة الدفع:
  - نقدي.
  - آجل.
  - تحويل.
  - محفظة.
- ملاحظات.
- زر حفظ.
- زر طباعة أو حفظ PDF إن أمكن.

القواعد:
- كل فاتورة تحفظ أولًا محليًا في SQLite.
- إذا كان Online يحاول رفعها فورًا.
- إذا فشلت المزامنة تبقى Pending Sync.
- عند الحفظ Offline يتم تقليل الكمية المحلية فورًا.
- يجب إنشاء local_uuid لكل فاتورة.
- يجب إنشاء idempotency_key لمنع التكرار.

---

### 5. شاشة العملاء
تحتوي على:
- قائمة العملاء المخزنين محليًا.
- بحث بالاسم أو الهاتف.
- إضافة عميل جديد.
- تعديل بيانات عميل محلي إذا كان مسموحًا.
- عرض حالة المزامنة.

القواعد:
- العميل الجديد Offline يأخذ local_uuid.
- عند المزامنة يتم إنشاء العميل على السيرفر أو ربطه بعميل موجود إذا كان نفس رقم الهاتف موجودًا.
- بعد نجاح المزامنة يتم حفظ server_id محليًا.

---

### 6. شاشة التحصيلات
تحتوي على:
- اختيار العميل أو الفاتورة.
- إدخال المبلغ.
- طريقة التحصيل.
- ملاحظات.
- حفظ محلي.
- حالة المزامنة.

---

### 7. شاشة المرتجعات
تحتوي على:
- اختيار فاتورة.
- اختيار صنف.
- اختيار كمية.
- سبب المرتجع.
- تحديد هل الصنف سليم أم تالف.
- تحديد هل يرجع للمخزون أم لا.
- حفظ محلي.
- حالة المزامنة.

القواعد:
- إذا كان الصنف سليمًا ويرجع للمخزون، تتم زيادة local_stock.
- إذا كان تالفًا، لا تتم زيادة المخزون المتاح أو يتم تسجيله كمخزون تالف حسب تصميم المشروع الحالي.

---

### 8. شاشة سجل المزامنة
تعرض:
- العمليات المنتظرة.
- العمليات التي تمت مزامنتها.
- العمليات الفاشلة.
- سبب الفشل.
- وقت آخر محاولة.
- عدد المحاولات.
- زر إعادة المحاولة.
- تفاصيل JSON مختصرة للعملية للمسؤول فقط.

---

### 9. شاشة الإعدادات
تحتوي على:
- API Base URL.
- حالة الاتصال.
- زر مزامنة يدوية.
- زر تحميل البيانات الأساسية.
- زر تصدير نسخة احتياطية محلية.
- زر عرض معلومات الجهاز.
- Device ID.
- إصدار التطبيق.

---

## قاعدة البيانات المحلية SQLite
أنشئ ملف schema داخل:

```txt
desktop_app/database/schema.sql
```

ويحتوي على الجداول التالية كحد أدنى:

```sql
CREATE TABLE users (
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

CREATE TABLE products (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  server_id INTEGER UNIQUE,
  name TEXT NOT NULL,
  sku TEXT,
  category TEXT,
  is_active INTEGER DEFAULT 1,
  updated_at TEXT
);

CREATE TABLE product_variants (
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
  updated_at TEXT
);

CREATE TABLE local_stock (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  variant_server_id INTEGER,
  local_variant_id INTEGER,
  warehouse_server_id INTEGER,
  quantity REAL DEFAULT 0,
  min_quantity REAL DEFAULT 0,
  updated_at TEXT
);

CREATE TABLE customers (
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
  updated_at TEXT,
  deleted_at TEXT
);

CREATE TABLE orders (
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
  sync_status TEXT DEFAULT 'pending',
  sync_error TEXT,
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE order_items (
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

CREATE TABLE payment_transactions (
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

CREATE TABLE returns (
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

CREATE TABLE sync_queue (
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

CREATE TABLE sync_meta (
  key TEXT PRIMARY KEY,
  value TEXT
);
```

يمكن إضافة جداول أخرى عند الحاجة، مثل:

```txt
stock_movements
app_settings
devices
conflicts
audit_logs
```

---

## Offline-first Rules
يجب الالتزام بالقواعد التالية:

1. كل عملية مهمة تحفظ أولًا محليًا.
2. لا تعتمد الواجهة على الاتصال بالسيرفر حتى تعمل.
3. عند وجود إنترنت يتم رفع العملية بعد حفظها محليًا.
4. إذا فشل الرفع تبقى العملية في `sync_queue`.
5. لا تفقد أي عملية محلية مهما حدث.
6. لا تحذف عملية فاشلة تلقائيًا.
7. يجب إظهار حالة واضحة للمستخدم:
   - محفوظ محليًا.
   - بانتظار المزامنة.
   - تمت المزامنة.
   - فشل بسبب تعارض.
   - فشل بسبب خطأ اتصال.

---

## آلية المزامنة المطلوبة
أنشئ Sync Service في:

```txt
desktop_app/src/renderer/js/syncService.js
```

وظائفه:

1. فحص الاتصال كل 30 ثانية.
2. تشغيل المزامنة تلقائيًا عند عودة الاتصال.
3. منع تشغيل أكثر من مزامنة في نفس الوقت.
4. رفع العمليات حسب الترتيب التالي:
   1. العملاء الجدد.
   2. الفواتير.
   3. عناصر الفواتير إن كانت منفصلة.
   4. التحصيلات.
   5. المرتجعات.
   6. حركات المخزون المحلية.
5. استخدام idempotency_key لكل عملية.
6. بعد نجاح مزامنة العميل، يتم تحديث أي سجلات كانت تستخدم `customer_local_uuid`.
7. بعد نجاح مزامنة الفاتورة، يتم تحديث أي تحصيلات أو مرتجعات مرتبطة بها.
8. بعد كل مزامنة ناجحة، يتم تحديث `last_sync_at` في `sync_meta`.
9. بعد كل مزامنة، يتم تنفيذ Pull Changes من السيرفر.

---

## API المطلوب في Django Server
إذا لم تكن هذه endpoints موجودة، أضفها بشكل منظم في app جديد مثل:

```txt
sync_api/
```

### Authentication
```txt
POST /api/auth/login/
POST /api/auth/refresh/
GET  /api/auth/me/
```

### Bootstrap
```txt
GET /api/sync/bootstrap/
```

يرجع:
- بيانات المستخدم.
- الصلاحيات.
- المنتجات.
- المتغيرات.
- العملاء المسموحين.
- مخزون عهدة المستخدم.
- إعدادات الشركة.
- آخر أرقام أو بادئات الفواتير.

### Pull Changes
```txt
GET /api/sync/changes/?since=<timestamp>
```

يرجع أي تغييرات حدثت على السيرفر منذ آخر مزامنة.

### Push Changes
```txt
POST /api/sync/push/
```

يستقبل قائمة عمليات بالشكل التالي:

```json
[
  {
    "idempotency_key": "device-order-uuid-create",
    "entity_type": "order",
    "operation_type": "create",
    "local_uuid": "local-uuid",
    "device_id": "device-id",
    "created_at": "2026-06-20T10:00:00Z",
    "payload": {}
  }
]
```

ويرجع:

```json
[
  {
    "local_uuid": "local-uuid",
    "status": "success",
    "server_id": 123
  },
  {
    "local_uuid": "local-uuid-2",
    "status": "failed_conflict",
    "error": "Insufficient stock"
  }
]
```

---

## Idempotency على السيرفر
أضف جدولًا في Django باسم:

```txt
sync_operations
```

ويحتوي على:

```txt
id
idempotency_key unique
device_id
user
entity_type
operation_type
local_uuid
server_model
server_object_id
payload_hash
status
response_json
created_at
updated_at
```

القواعد:
- إذا وصل نفس `idempotency_key` مرة أخرى، لا يتم إنشاء العملية مرة ثانية.
- يرجع السيرفر نفس الرد السابق.
- هذا ضروري جدًا لمنع تكرار الفواتير أو التحصيلات عند انقطاع الاتصال أثناء المزامنة.

---

## Conflict Handling
يجب التعامل مع التعارضات بهذا الشكل:

1. إذا تغير السعر على السيرفر أثناء Offline:
   - لا تعدل الفاتورة المحلية القديمة تلقائيًا.
   - ارفع الفاتورة بالأسعار التي حفظها المستخدم.
   - السيرفر يقرر قبولها أو رفضها حسب الصلاحيات.

2. إذا كانت الكمية على السيرفر غير كافية:
   - ترجع العملية `failed_conflict`.
   - تبقى الفاتورة محليًا.
   - تظهر في شاشة سجل المزامنة.
   - لا يتم حذفها.

3. إذا تم إنشاء عميل بنفس رقم الهاتف:
   - لا تنشئ عميلًا مكررًا.
   - اربط العميل المحلي بالعميل الموجود إذا كان ذلك آمنًا.

4. إذا تم حذف أو تعطيل منتج على السيرفر:
   - امنع استخدامه في عمليات جديدة بعد آخر Pull.
   - لا تحذف العمليات القديمة التي استخدمته.

5. لا تفقد أي عملية محلية حتى لو فشلت المزامنة.

---

## إدارة المخزون المحلي
عند إنشاء فاتورة Offline:

1. قلل الكمية من `local_stock` فورًا.
2. سجل حركة محلية مرتبطة بالفاتورة.
3. ضع الفاتورة في حالة `pending_sync`.
4. أضف العملية إلى `sync_queue`.

إذا فشلت مزامنة الفاتورة بسبب نقص مخزون على السيرفر:

1. لا تحذف الفاتورة المحلية.
2. ضعها في حالة `conflict`.
3. أظهر رسالة واضحة للمستخدم.
4. وفر زر إعادة المحاولة بعد تحديث البيانات.
5. يمكن إضافة خيار إرسالها للمدير للمراجعة لاحقًا.

عند مرتجع Offline:

1. إذا الصنف سليم ويرجع للمخزون، زد `local_stock`.
2. إذا تالف، لا تزده في المخزون المتاح.
3. احفظ المرتجع محليًا.
4. أضفه إلى `sync_queue`.

---

## الأمان
يجب الالتزام بما يلي:

1. لا تخزن كلمة المرور نصًا صريحًا.
2. خزّن token بشكل مشفر باستخدام Electron `safeStorage` إن أمكن.
3. استخدم HTTPS فقط مع السيرفر.
4. أضف `device_id` ثابت لكل جهاز.
5. أضف `idempotency_key` لكل عملية sync.
6. امنع الوصول للواجهة إذا لم يكن هناك Login سابق.
7. احترم صلاحيات المستخدم القادمة من السيرفر.
8. لا تعرض التكلفة أو الربح إلا للمدير أو من يملك الصلاحية.
9. امنع تنفيذ عمليات غير مسموحة حتى لو حاول المستخدم من الواجهة.
10. أعد التحقق من الصلاحيات على السيرفر أيضًا.

---

## تجربة المستخدم
التطبيق يجب أن يكون واضحًا للمستخدم غير التقني.

استخدم رسائل مثل:

```txt
تم الحفظ على السيرفر
تم الحفظ محليًا بانتظار المزامنة
فشلت المزامنة، راجع سجل المزامنة
لا يوجد اتصال بالإنترنت، يمكنك الاستمرار وسيتم الحفظ محليًا
تمت المزامنة بنجاح
يوجد تعارض يحتاج مراجعة
```

ممنوع استخدام مصطلحات تقنية صعبة داخل شاشة البيع مثل:

```txt
payload
idempotency
sync_queue
JSON
```

هذه المصطلحات تظهر فقط في شاشة سجل المزامنة للمسؤول أو في ملفات التوثيق.

---

## متطلبات جودة الكود
1. استخدم JavaScript منظم مع `async/await`.
2. افصل منطق الواجهة عن منطق قاعدة البيانات.
3. افصل منطق المزامنة عن الشاشات.
4. استخدم Repositories لكل كيان.
5. أضف Error Handling واضح.
6. أضف Loading / Empty / Error states.
7. أضف Logging محلي داخل مجلد `logs`.
8. اجعل أسماء الملفات والدوال واضحة.
9. لا تضع كل الكود في ملف واحد.
10. اكتب تعليقات مختصرة فقط عند الحاجة.

---

## المطلوب تنفيذه في Django Server
بعد تحليل المشروع الحالي، إذا كانت APIs غير موجودة، أنشئ:

```txt
sync_api/
  __init__.py
  apps.py
  models.py
  serializers.py
  views.py
  urls.py
  services.py
  permissions.py
```

ويجب أن يحتوي على:

1. Login API أو استخدام النظام الحالي إن كان موجودًا.
2. Bootstrap API.
3. Changes API.
4. Push API.
5. SyncOperation model.
6. Idempotency handling.
7. Conflict handling.
8. ربط آمن مع موديلات المشروع الحالية.

لا تنسَ إضافة urls الخاصة به داخل urls الرئيسي بطريقة لا تكسر الموقع.

---

## ملف README المطلوب داخل desktop_app
أنشئ ملف:

```txt
desktop_app/README.md
```

ويحتوي على:

1. وصف التطبيق.
2. طريقة التشغيل.
3. طريقة تثبيت dependencies.
4. طريقة إعداد API Base URL.
5. طريقة إنشاء قاعدة SQLite.
6. طريقة تشغيل التطبيق في وضع التطوير.
7. طريقة بناء نسخة Production.
8. شرح مختصر للمزامنة.
9. شرح Offline mode.
10. سيناريوهات الاختبار.

---

## أوامر التشغيل المقترحة
داخل مجلد `desktop_app`:

```bash
npm install
npm run dev
npm run build
```

ويجب ضبط `package.json` ليحتوي على scripts واضحة مثل:

```json
{
  "scripts": {
    "dev": "electron .",
    "start": "electron .",
    "build": "electron-builder",
    "lint": "echo \"Add lint later\"",
    "test": "echo \"Add tests later\""
  }
}
```

---

## سيناريوهات الاختبار المطلوبة
اختبر السيناريوهات التالية ودوّن النتيجة في:

```txt
desktop_app/docs/testing-scenarios.md
```

السيناريوهات:

1. تسجيل الدخول Online.
2. تسجيل الدخول Offline بعد Login سابق.
3. فشل تسجيل الدخول Offline بدون Login سابق.
4. تحميل البيانات الأساسية Bootstrap.
5. عرض المنتجات بدون إنترنت.
6. إنشاء عميل Offline ثم مزامنته.
7. إنشاء فاتورة Offline ثم مزامنتها.
8. إنشاء تحصيل Offline ثم مزامنته.
9. إنشاء مرتجع Offline ثم مزامنته.
10. فشل مزامنة فاتورة بسبب نقص مخزون.
11. عدم تكرار الفاتورة عند إعادة إرسال نفس العملية.
12. انقطاع الاتصال أثناء المزامنة ثم استكمالها.
13. Pull Changes بعد نجاح Push.
14. منع مستخدم بدون صلاحية من رؤية التكلفة أو الربح.
15. تصدير نسخة احتياطية محلية.

---

## معايير القبول النهائية
يعتبر التنفيذ صحيحًا فقط إذا تحقق الآتي:

- تم إنشاء مجلد `desktop_app` داخل مسار المشروع الحالي.
- لم يتم كسر الموقع الرئيسي.
- التطبيق يفتح كـ Electron Desktop App.
- الواجهة عربية بالكامل RTL.
- التصميم قريب من لوحة ERP الحالية.
- تسجيل الدخول Online يعمل.
- تسجيل الدخول Offline بعد Login سابق يعمل.
- المنتجات والعملاء والمخزون تظهر Offline.
- إنشاء فاتورة Offline يعمل.
- الكمية المحلية تقل بعد الفاتورة.
- العمليات تحفظ في SQLite.
- العمليات تدخل `sync_queue`.
- المزامنة تعمل عند عودة الاتصال.
- لا يتم تكرار الفواتير أو التحصيلات.
- التعارضات تظهر بوضوح ولا يتم حذف البيانات.
- يوجد README واضح.
- يوجد توثيق للمزامنة والاختبارات.

---

## ملاحظات مهمة للمطور أو AI Agent
- لا تبدأ بكتابة كود عشوائي.
- ابدأ بتحليل المشروع الحالي.
- لا تنشئ ERP جديد منفصل.
- لا تكرر منطق Django الحالي في Electron إلا عند الحاجة للعمل Offline.
- استخدم SQLite فقط للتخزين المحلي.
- السيرفر هو مصدر الحقيقة النهائي بعد المزامنة.
- التطبيق المحلي مصدر مؤقت آمن أثناء عدم وجود إنترنت.
- لا تفقد أي عملية محلية.
- لا تثق في الواجهة فقط؛ تحقق من الصلاحيات في السيرفر.
- اجعل الكود قابلًا للتوسع مستقبلًا.

---

## المطلوب في نهاية التنفيذ
بعد الانتهاء، قدم تقريرًا مختصرًا يحتوي على:

1. ما الذي تم إنشاؤه داخل `desktop_app`.
2. ما الذي تم تعديله في Django إن وجد.
3. أسماء ملفات APIs الجديدة.
4. طريقة تشغيل تطبيق الديسكتوب.
5. طريقة اختبار Offline mode.
6. طريقة اختبار المزامنة.
7. أي نقاط لم تكتمل أو تحتاج قرارًا من صاحب المشروع.
