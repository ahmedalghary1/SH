# طباعة الفواتير الحرارية

تم فصل صفحة طباعة الفاتورة عن قالب النظام العام حتى تكون مناسبة للطابعات الحرارية. المسار المستخدم هو:

```txt
/invoices/<invoice_id>/print/
```

## إعدادات النظام

من صفحة الإعدادات اختر:

- مقاس ورق طابعة الفواتير: `80 مم` أو `58 مم`.
- طريقة طباعة الفواتير:
  - `طباعة المتصفح`: تعمل فورًا من أي متصفح.
  - `طباعة مباشرة عبر تطبيق سطح المكتب`: تحتاج جسر Electron.
  - `طباعة مباشرة عبر QZ Tray`: تحتاج تحميل مكتبة QZ Tray في الصفحة وتفعيل QZ على الجهاز.
- اسم الطابعة الحرارية: يفضل أن يطابق اسم الطابعة في Windows مثل `POS-80`.

إذا تعذرت الطباعة المباشرة، ترجع الصفحة تلقائيًا إلى طباعة المتصفح.

## جسر Electron

صفحة الطباعة تبحث عن كائن JavaScript باسم `window.shDesktopPrinter`. في ملف `preload.js` الخاص بتطبيق Electron عرّف الجسر بهذا الشكل:

```js
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("shDesktopPrinter", {
  printHtml(payload) {
    return ipcRenderer.invoke("thermal-print", payload);
  },
});
```

وفي `main.js`:

```js
const { BrowserWindow, ipcMain } = require("electron");

ipcMain.handle("thermal-print", async (event, payload) => {
  const printWindow = new BrowserWindow({
    show: false,
    webPreferences: {
      offscreen: true,
    },
  });

  await printWindow.loadURL(
    `data:text/html;charset=utf-8,${encodeURIComponent(payload.html)}`
  );

  await new Promise((resolve, reject) => {
    printWindow.webContents.print(
      {
        silent: true,
        deviceName: payload.printerName || undefined,
        printBackground: true,
        preferCSSPageSize: true,
        margins: { marginType: "none" },
        pageSize: {
          width: payload.paperWidth * 1000,
          height: Math.ceil((payload.pageHeight || payload.receiptHeight || 80) * 1000),
        },
      },
      (success, failureReason) => {
        printWindow.close();
        if (success) resolve();
        else reject(new Error(failureReason || "Thermal print failed"));
      }
    );
  });

  return { ok: true };
});
```

## QZ Tray

للتشغيل عبر QZ Tray يجب توفير مكتبة QZ JavaScript داخل الصفحة قبل ضغط زر الطباعة، ثم اختيار `طباعة مباشرة عبر QZ Tray` من الإعدادات. الصفحة الحالية تتوقع وجود:

```js
window.qz
```

مع تهيئة الشهادات والتوقيع حسب إعداد QZ Tray في جهاز العميل.
