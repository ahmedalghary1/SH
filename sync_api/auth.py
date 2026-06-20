import json
from functools import wraps

from django.contrib.auth import authenticate, get_user_model
from django.core import signing
from django.http import JsonResponse


TOKEN_SALT = 'sync-api-token'
TOKEN_MAX_AGE = 60 * 60 * 24 * 30


def make_token(user, device_id=''):
    return signing.dumps({'user_id': user.pk, 'device_id': device_id}, salt=TOKEN_SALT)


def user_payload(user):
    return {
        'id': user.pk,
        'username': user.username,
        'full_name': user.get_full_name() or user.username,
        'role': getattr(user, 'role', ''),
        'permissions': {
            'is_manager': bool(getattr(user, 'is_manager', False)),
            'is_sales': bool(getattr(user, 'is_sales', False)),
            'is_warehouse': bool(getattr(user, 'is_warehouse', False)),
            'can_view_costs': bool(getattr(user, 'is_manager', False)),
        },
    }


def parse_json_body(request):
    try:
        return json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return None


def login_view(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    payload = parse_json_body(request)
    if payload is None:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    user = authenticate(request, username=payload.get('username'), password=payload.get('password'))
    if not user or not user.is_active:
        return JsonResponse({'error': 'بيانات الدخول غير صحيحة'}, status=401)
    token = make_token(user, payload.get('device_id') or '')
    return JsonResponse({'token': token, 'user': user_payload(user)})


def authenticate_token(request):
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return None
    token = auth_header.split(' ', 1)[1].strip()
    try:
        data = signing.loads(token, salt=TOKEN_SALT, max_age=TOKEN_MAX_AGE)
    except signing.BadSignature:
        return None
    return get_user_model().objects.filter(pk=data.get('user_id'), is_active=True).first()


def token_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = authenticate_token(request)
        if not user:
            return JsonResponse({'error': 'Authentication required'}, status=401)
        request.sync_user = user
        return view_func(request, *args, **kwargs)
    return wrapper


@token_required
def me_view(request):
    return JsonResponse({'user': user_payload(request.sync_user)})


@token_required
def refresh_view(request):
    device_id = ''
    payload = parse_json_body(request) if request.method == 'POST' and request.body else {}
    if payload:
        device_id = payload.get('device_id') or ''
    return JsonResponse({'token': make_token(request.sync_user, device_id), 'user': user_payload(request.sync_user)})
