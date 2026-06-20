# عقد API للمزامنة

## Login
`POST /api/auth/login/`

Body:
```json
{"username":"user","password":"pass","device_id":"uuid"}
```

## Refresh
`POST /api/auth/refresh/`

Headers:
`Authorization: Bearer <token>`

## Bootstrap
`GET /api/sync/bootstrap/`

Headers:
`Authorization: Bearer <token>`

يرجع المستخدم، الصلاحيات، المنتجات، المتغيرات، العملاء، المخزون، وإعدادات الشركة.

## Push
`POST /api/sync/push/`

## Ping
`GET /api/sync/ping/`

يرجع:
```json
{"status":"ok"}
```

Body:
```json
[
  {
    "idempotency_key": "device-local-create",
    "entity_type": "order",
    "operation_type": "create",
    "local_uuid": "uuid",
    "device_id": "device",
    "created_at": "2026-06-20T10:00:00Z",
    "payload": {}
  }
]
```

Response:
```json
[
  {"local_uuid":"uuid","status":"success","server_id":123},
  {"local_uuid":"uuid2","status":"failed_conflict","error":"Insufficient stock"}
]
```
