# SH ERP Desktop

تطبيق ديسكتوب عربي يعمل Online و Offline لنظام SH ERP.

## التقنية
- Electron
- HTML / CSS / JavaScript
- SQLite محلي عبر `better-sqlite3`
- Sync API مضاف إلى Django في `sync_api`

## التشغيل
من داخل مجلد `desktop_app`:

```bash
npm install
npm run dev
```

## الإعداد
افتح شاشة الإعدادات داخل التطبيق واضبط:

```text
API Base URL=https://sh.elwsamstore.com
```

أو رابط السيرفر الفعلي عند التشغيل على الإنتاج.

## وضع Offline
يجب تسجيل الدخول مرة واحدة Online حتى يتم حفظ token محليًا بشكل مشفر. بعد ذلك يمكن الدخول Offline بنفس المستخدم، وتسجيل العملاء والفواتير والتحصيلات والمرتجعات محليًا.

## المزامنة
التطبيق يحفظ العمليات في `sync_queue` ثم يحاول رفعها إلى:

```text
POST /api/sync/push/
```

ويستخدم `idempotency_key` لمنع تكرار الفواتير أو التحصيلات عند إعادة المحاولة.

## بناء نسخة Production

```bash
npm run build
```

## ملاحظات
- السيرفر هو مصدر الحقيقة النهائي.
- عند تعارض المخزون تبقى الفاتورة محليًا بحالة conflict ولا يتم حذفها.
- لا تعرض التكلفة في التطبيق إلا حسب الصلاحيات القادمة من السيرفر.
