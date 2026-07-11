from django.db import IntegrityError
from django.http import JsonResponse

from .models import SubmissionReceipt


class DuplicateSubmissionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = request.POST.get('_submission_token') if request.method == 'POST' else None
        receipt = None
        if token and request.user.is_authenticated:
            try:
                receipt = SubmissionReceipt.objects.create(token=token[:64], user=request.user, path=request.path[:255])
            except IntegrityError:
                return JsonResponse({'success': False, 'duplicate': True, 'message': 'تم استلام هذا الطلب من قبل ولن يتم تكرار الحفظ.'}, status=409)
        response = self.get_response(request)
        if receipt and response.status_code >= 400:
            receipt.delete()
        return response
