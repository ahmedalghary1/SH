from django.http import HttpResponse, JsonResponse
from django.urls import reverse


API_TITLE = 'SH Sync API'
API_VERSION = '1.0.0'


def _api_url(request, name):
    return request.build_absolute_uri(reverse(name))


def openapi_schema(request):
    if request.method != 'GET':
        response = JsonResponse({'error': 'Method not allowed'}, status=405)
        response['Allow'] = 'GET'
        return response
    security = [{'bearerAuth': []}]
    schema = {
        'openapi': '3.0.3',
        'info': {
            'title': API_TITLE,
            'version': API_VERSION,
            'description': 'API used by the offline/desktop sync client.',
        },
        'servers': [
            {
                'url': request.build_absolute_uri('/api/').rstrip('/'),
                'description': 'Current server',
            },
        ],
        'tags': [
            {'name': 'Health'},
            {'name': 'Auth'},
            {'name': 'Sync'},
        ],
        'paths': {
            '/sync/ping/': {
                'get': {
                    'tags': ['Health'],
                    'summary': 'Ping the sync API',
                    'responses': {
                        '200': {
                            'description': 'API is reachable',
                            'content': {
                                'application/json': {
                                    'schema': {'$ref': '#/components/schemas/PingResponse'},
                                },
                            },
                        },
                    },
                },
            },
            '/auth/login/': {
                'post': {
                    'tags': ['Auth'],
                    'summary': 'Login and get a bearer token',
                    'requestBody': {
                        'required': True,
                        'content': {
                            'application/json': {
                                'schema': {'$ref': '#/components/schemas/LoginRequest'},
                            },
                        },
                    },
                    'responses': {
                        '200': {'$ref': '#/components/responses/AuthTokenResponse'},
                        '400': {'$ref': '#/components/responses/ErrorResponse'},
                        '401': {'$ref': '#/components/responses/ErrorResponse'},
                        '405': {'$ref': '#/components/responses/ErrorResponse'},
                    },
                },
            },
            '/auth/refresh/': {
                'post': {
                    'tags': ['Auth'],
                    'summary': 'Refresh a bearer token',
                    'security': security,
                    'requestBody': {
                        'required': False,
                        'content': {
                            'application/json': {
                                'schema': {'$ref': '#/components/schemas/RefreshRequest'},
                            },
                        },
                    },
                    'responses': {
                        '200': {'$ref': '#/components/responses/AuthTokenResponse'},
                        '400': {'$ref': '#/components/responses/ErrorResponse'},
                        '401': {'$ref': '#/components/responses/ErrorResponse'},
                        '405': {'$ref': '#/components/responses/ErrorResponse'},
                    },
                },
            },
            '/auth/me/': {
                'get': {
                    'tags': ['Auth'],
                    'summary': 'Get the authenticated user',
                    'security': security,
                    'responses': {
                        '200': {
                            'description': 'Authenticated user',
                            'content': {
                                'application/json': {
                                    'schema': {
                                        'type': 'object',
                                        'properties': {
                                            'user': {'$ref': '#/components/schemas/User'},
                                        },
                                    },
                                },
                            },
                        },
                        '401': {'$ref': '#/components/responses/ErrorResponse'},
                        '405': {'$ref': '#/components/responses/ErrorResponse'},
                    },
                },
            },
            '/sync/bootstrap/': {
                'get': {
                    'tags': ['Sync'],
                    'summary': 'Load the initial sync payload',
                    'security': security,
                    'responses': {
                        '200': {'$ref': '#/components/responses/BootstrapResponse'},
                        '401': {'$ref': '#/components/responses/ErrorResponse'},
                        '405': {'$ref': '#/components/responses/ErrorResponse'},
                    },
                },
            },
            '/sync/changes/': {
                'get': {
                    'tags': ['Sync'],
                    'summary': 'Load changed sync data',
                    'security': security,
                    'parameters': [
                        {
                            'name': 'since',
                            'in': 'query',
                            'required': False,
                            'schema': {'type': 'string', 'format': 'date-time'},
                            'description': 'ISO datetime. When omitted, the endpoint returns the bootstrap payload.',
                        },
                    ],
                    'responses': {
                        '200': {'$ref': '#/components/responses/BootstrapResponse'},
                        '400': {'$ref': '#/components/responses/ErrorResponse'},
                        '401': {'$ref': '#/components/responses/ErrorResponse'},
                        '405': {'$ref': '#/components/responses/ErrorResponse'},
                    },
                },
            },
            '/sync/push/': {
                'post': {
                    'tags': ['Sync'],
                    'summary': 'Push offline operations',
                    'security': security,
                    'requestBody': {
                        'required': True,
                        'content': {
                            'application/json': {
                                'schema': {
                                    'type': 'array',
                                    'items': {'$ref': '#/components/schemas/SyncOperation'},
                                },
                            },
                        },
                    },
                    'responses': {
                        '200': {
                            'description': 'Operation results',
                            'content': {
                                'application/json': {
                                    'schema': {
                                        'type': 'array',
                                        'items': {'$ref': '#/components/schemas/SyncOperationResult'},
                                    },
                                },
                            },
                        },
                        '400': {'$ref': '#/components/responses/ErrorResponse'},
                        '401': {'$ref': '#/components/responses/ErrorResponse'},
                        '405': {'$ref': '#/components/responses/ErrorResponse'},
                    },
                },
            },
            '/schema/': {
                'get': {
                    'tags': ['Health'],
                    'summary': 'OpenAPI schema',
                    'responses': {'200': {'description': 'OpenAPI JSON document'}},
                },
            },
            '/docs/': {
                'get': {
                    'tags': ['Health'],
                    'summary': 'Swagger UI',
                    'responses': {'200': {'description': 'Swagger UI HTML'}},
                },
            },
        },
        'components': {
            'securitySchemes': {
                'bearerAuth': {
                    'type': 'http',
                    'scheme': 'bearer',
                },
            },
            'responses': {
                'AuthTokenResponse': {
                    'description': 'Token and user payload',
                    'content': {
                        'application/json': {
                            'schema': {
                                'type': 'object',
                                'required': ['token', 'user'],
                                'properties': {
                                    'token': {'type': 'string'},
                                    'user': {'$ref': '#/components/schemas/User'},
                                },
                            },
                        },
                    },
                },
                'BootstrapResponse': {
                    'description': 'Sync payload',
                    'content': {
                        'application/json': {
                            'schema': {'$ref': '#/components/schemas/BootstrapPayload'},
                        },
                    },
                },
                'ErrorResponse': {
                    'description': 'Error payload',
                    'content': {
                        'application/json': {
                            'schema': {'$ref': '#/components/schemas/Error'},
                        },
                    },
                },
            },
            'schemas': {
                'Error': {
                    'type': 'object',
                    'properties': {'error': {'type': 'string'}},
                },
                'PingResponse': {
                    'type': 'object',
                    'properties': {'status': {'type': 'string', 'example': 'ok'}},
                },
                'LoginRequest': {
                    'type': 'object',
                    'required': ['username', 'password'],
                    'properties': {
                        'username': {'type': 'string'},
                        'password': {'type': 'string', 'format': 'password'},
                        'device_id': {'type': 'string'},
                    },
                },
                'RefreshRequest': {
                    'type': 'object',
                    'properties': {'device_id': {'type': 'string'}},
                },
                'User': {
                    'type': 'object',
                    'properties': {
                        'id': {'type': 'integer'},
                        'username': {'type': 'string'},
                        'full_name': {'type': 'string'},
                        'role': {'type': 'string'},
                        'permissions': {'$ref': '#/components/schemas/UserPermissions'},
                    },
                },
                'UserPermissions': {
                    'type': 'object',
                    'properties': {
                        'is_manager': {'type': 'boolean'},
                        'is_sales': {'type': 'boolean'},
                        'is_warehouse': {'type': 'boolean'},
                        'can_view_costs': {'type': 'boolean'},
                    },
                },
                'BootstrapPayload': {
                    'type': 'object',
                    'properties': {
                        'user': {'$ref': '#/components/schemas/User'},
                        'permissions': {'$ref': '#/components/schemas/UserPermissions'},
                        'company': {'type': 'object'},
                        'cash': {'type': 'object'},
                        'products': {'type': 'array', 'items': {'$ref': '#/components/schemas/Product'}},
                        'variants': {'type': 'array', 'items': {'$ref': '#/components/schemas/ProductVariant'}},
                        'customers': {'type': 'array', 'items': {'$ref': '#/components/schemas/Customer'}},
                        'orders': {'type': 'array', 'items': {'$ref': '#/components/schemas/Order'}},
                        'stock': {'type': 'array', 'items': {'$ref': '#/components/schemas/Stock'}},
                    },
                },
                'Product': {
                    'type': 'object',
                    'properties': {
                        'id': {'type': 'integer'},
                        'name': {'type': 'string'},
                        'sku': {'type': 'string'},
                        'category': {'type': 'string'},
                        'is_active': {'type': 'boolean'},
                        'updated_at': {'type': 'string', 'format': 'date-time'},
                    },
                },
                'ProductVariant': {
                    'type': 'object',
                    'properties': {
                        'id': {'type': 'integer'},
                        'product_id': {'type': 'integer'},
                        'color': {'type': 'string'},
                        'size': {'type': 'string'},
                        'variant_sku': {'type': 'string'},
                        'barcode': {'type': 'string'},
                        'sale_price': {'type': 'string'},
                        'cost_price': {'type': 'string'},
                        'image_url': {'type': 'string'},
                        'is_active': {'type': 'boolean'},
                        'updated_at': {'type': 'string'},
                    },
                },
                'Customer': {
                    'type': 'object',
                    'properties': {
                        'id': {'type': 'integer'},
                        'local_uuid': {'type': 'string'},
                        'name': {'type': 'string'},
                        'phone': {'type': 'string'},
                        'whatsapp': {'type': 'string'},
                        'customer_type': {'type': 'string'},
                        'address': {'type': 'string'},
                        'credit_limit': {'type': 'string'},
                        'opening_balance': {'type': 'string'},
                        'updated_at': {'type': 'string', 'format': 'date-time'},
                    },
                },
                'Order': {
                    'type': 'object',
                    'properties': {
                        'id': {'type': 'integer'},
                        'local_uuid': {'type': 'string'},
                        'order_number': {'type': 'string'},
                        'customer_id': {'type': 'integer', 'nullable': True},
                        'customer_local_uuid': {'type': 'string'},
                        'document_type': {'type': 'string'},
                        'order_type': {'type': 'string'},
                        'status': {'type': 'string'},
                        'payment_status': {'type': 'string'},
                        'payment_method': {'type': 'string'},
                        'subtotal': {'type': 'string'},
                        'discount': {'type': 'string'},
                        'total': {'type': 'string'},
                        'paid_amount': {'type': 'string'},
                        'remaining_amount': {'type': 'string'},
                        'notes': {'type': 'string'},
                        'created_by_id': {'type': 'integer', 'nullable': True},
                        'created_by_name': {'type': 'string'},
                        'created_at': {'type': 'string', 'format': 'date-time'},
                        'updated_at': {'type': 'string', 'format': 'date-time'},
                    },
                },
                'Stock': {
                    'type': 'object',
                    'properties': {
                        'variant_id': {'type': 'integer'},
                        'warehouse_id': {'type': 'integer'},
                        'warehouse_name': {'type': 'string'},
                        'quantity': {'type': 'integer'},
                        'min_quantity': {'type': 'integer'},
                        'updated_at': {'type': 'string'},
                    },
                },
                'SyncOperation': {
                    'type': 'object',
                    'required': ['idempotency_key', 'local_uuid', 'entity_type', 'operation_type', 'payload'],
                    'properties': {
                        'idempotency_key': {'type': 'string'},
                        'device_id': {'type': 'string'},
                        'entity_type': {'type': 'string', 'enum': ['customer', 'order', 'payment', 'return']},
                        'operation_type': {'type': 'string', 'example': 'create'},
                        'local_uuid': {'type': 'string'},
                        'payload': {'type': 'object'},
                    },
                },
                'SyncOperationResult': {
                    'type': 'object',
                    'properties': {
                        'local_uuid': {'type': 'string'},
                        'status': {'type': 'string'},
                        'server_id': {'type': 'integer'},
                        'server_model': {'type': 'string'},
                        'error': {'type': 'string'},
                    },
                },
            },
        },
    }
    return JsonResponse(schema)


def swagger_ui(request):
    if request.method != 'GET':
        response = JsonResponse({'error': 'Method not allowed'}, status=405)
        response['Allow'] = 'GET'
        return response
    schema_url = _api_url(request, 'api_schema')
    html = f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{API_TITLE} Swagger</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
  <style>
    body {{ margin: 0; background: #fff; }}
    .swagger-ui {{ direction: ltr; }}
  </style>
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    window.ui = SwaggerUIBundle({{
      url: "{schema_url}",
      dom_id: "#swagger-ui",
      deepLinking: true,
      persistAuthorization: true,
      layout: "BaseLayout"
    }});
  </script>
</body>
</html>"""
    return HttpResponse(html)
