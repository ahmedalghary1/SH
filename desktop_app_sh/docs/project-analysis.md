# تحليل مشروع SH ERP الحالي

## الهيكل العام
المشروع الحالي تطبيق Django ERP عربي لإدارة تجارة الملابس. التطبيقات الرئيسية الموجودة:
`accounts`, `products`, `inventory`, `customers`, `orders`, `invoices`, `finance`, `purchases`, `returns`, `sales_reps`, `reports`, `dashboard`, `settings_app`, و `audit`.

## الإعدادات
ملف الإعدادات الفعلي هو `config/settings.py`. المشروع يستخدم قالب مشترك في `templates/base.html` وملف CSS رئيسي في `static/css/main.css`.

## الصلاحيات
المستخدم مخصص في `accounts.User` بأدوار:
- `manager` مسؤول النظام
- `director` المدير
- `sales` مندوب مبيعات
- `warehouse` مسؤول مخزن

توجد دوال صلاحيات في `accounts/permissions.py`. المدير والسوبر يوزر يمكنهما رؤية التكلفة والربح وإدارة المشتريات والمالية والإعدادات.

## الموديلات المرتبطة بالتطبيق المكتبي
- المنتجات: `Product`, `ProductVariant`, `Category`, `Color`, `Size`
- المخزون: `Warehouse`, `Stock`, `StockBatch`, `StockMovement`
- العملاء: `Customer`, `CustomerInteraction`
- الطلبات: `Order`, `OrderItem`
- المالية: `CashAccount`, `PaymentTransaction`
- المرتجعات: `SalesReturn`, `SalesReturnItem`, `ExchangeItem`
- المندوبون: `SalesRepStockAssignment`, `SalesRepCollection`
- التدقيق: `AuditLog`

## الواجهة الحالية المطلوب تقليدها
الواجهة RTL عربية، تستخدم خط Cairo، شريط جانبي يمين بتدرج كحلي، شريط علوي أزرق، خلفية رمادي فاتح، بطاقات وجداول بيضاء، وأزرار زرقاء. ألوان الهوية موجودة كمتغيرات CSS في `static/css/main.css`.

## APIs الموجودة
يوجد بعض Ajax داخل التطبيقات مثل البحث عن منتجات أو عملاء وفحص المخزون، لكن لا يوجد API مزامنة Offline-first شامل. لذلك تم إنشاء app جديد باسم `sync_api`.

## APIs الناقصة التي أضيفت
- `POST /api/auth/login/`
- `GET /api/auth/me/`
- `GET /api/sync/bootstrap/`
- `GET /api/sync/changes/`
- `POST /api/sync/push/`

## مخاطر التنفيذ
- يجب عدم تكرار الفواتير عند إعادة المحاولة، لذلك يستخدم السيرفر `idempotency_key`.
- السيرفر هو مصدر الحقيقة النهائي بعد المزامنة.
- لا يجب فقدان أي عملية محلية عند فشل المزامنة.
- أي تعارض مخزون يجب أن يعود كحالة conflict ولا يحذف العملية من الجهاز.
- بيانات قاعدة الإنتاج يجب نقلها إلى متغيرات بيئة وعدم إبقائها داخل `settings.py`.
