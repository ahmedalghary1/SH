from django.http import HttpResponse
from django.template.loader import render_to_string


def _error(request, status, title, message):
    # No request context processors: this must also render when the DB is down.
    html = render_to_string('errors/error.html', {
        'status': status, 'title': title, 'message': message,
        'request_id': getattr(request, 'request_id', ''),
    })
    response = HttpResponse(html, status=status)
    response['Cache-Control'] = 'no-store'
    return response


def bad_request(request, exception):
    return _error(request, 400, 'تعذر تنفيذ الطلب', 'راجع البيانات المدخلة ثم أعد المحاولة.')


def permission_denied(request, exception):
    return _error(request, 403, 'لا يمكنك تنفيذ هذه العملية', 'قد تكون الجلسة انتهت أو الحساب لا يملك الصلاحية المطلوبة. سجّل الدخول أو تواصل مع المسؤول.')


def page_not_found(request, exception):
    return _error(request, 404, 'الصفحة غير موجودة', 'ربما تغير الرابط أو لم يعد السجل متاحًا لهذا الحساب.')


def server_error(request):
    return _error(request, 500, 'تعذر إكمال العملية', 'احتفظ ببيانات النموذج ورقم المتابعة أدناه. راجع نتيجة العملية قبل إعادة الحفظ لتجنب تكرارها.')
