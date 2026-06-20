# توافق تطبيق الديسكتوب مع Sync API

## الاتصال
- التطبيق يستخدم `DEFAULT_API_BASE_URL=https://sh.elwsamstore.com`.
- فحص الاتصال يستخدم `GET /api/sync/ping/`.
- `sync_api.middleware.SyncApiCorsMiddleware` يضيف CORS ويدعم preflight `OPTIONS` لمسارات `/api/` حتى تعمل طلبات Electron من `file://`.

## المصادقة
- شاشة الدخول تستدعي `POST /api/auth/login/`.
- التطبيق يخزن token محليًا ويستخدمه في `Authorization: Bearer <token>`.
- السيرفر يوفر `GET /api/auth/me/` و `POST /api/auth/refresh/`.

## تحميل البيانات
- التطبيق يستدعي `GET /api/sync/bootstrap/`.
- السيرفر يرجع: المستخدم، الصلاحيات، بيانات الشركة، المنتجات، المتغيرات، العملاء، والمخزون.
- أسماء الحقول متوافقة مع مستودعات التطبيق:
  - `products` -> `replaceProducts`
  - `variants` -> `replaceProducts`
  - `customers` -> `replaceCustomers`
  - `stock` -> `replaceStock`

## رفع العمليات
- التطبيق يرفع العمليات إلى `POST /api/sync/push/`.
- كل عملية تحتوي:
  - `idempotency_key`
  - `entity_type`
  - `operation_type`
  - `local_uuid`
  - `device_id`
  - `created_at`
  - `payload`
- السيرفر يدعم الكيانات الحالية: `customer`, `order`, `payment`, `return`.

## منع التكرار
- السيرفر يستخدم `SyncOperation.idempotency_key` كقيمة unique.
- إذا وصلت نفس العملية مرة أخرى، يرجع نفس `response_json` دون إنشاء عملية جديدة.

## التحديثات
- التطبيق يستدعي `GET /api/sync/changes/?since=<timestamp>`.
- السيرفر يرجع نفس شكل بيانات `bootstrap` حتى تبقى عملية الدمج المحلية بسيطة ومتوافقة.
