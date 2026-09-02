from django.db import IntegrityError
from django.http import JsonResponse

from config.branching import reset_current_branch, set_current_branch


class BranchContextMiddleware:
    """Select the immutable branch scope used by branch-aware model managers."""

    SESSION_KEY = "active_branch_id"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        branch_id = None
        request.active_branch = None
        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            if user.is_superuser:
                selected = request.session.get(self.SESSION_KEY)
                if selected:
                    from .models import Branch
                    request.active_branch = Branch.objects.filter(pk=selected, is_active=True).first()
                    branch_id = request.active_branch.pk if request.active_branch else None
            else:
                branch_id = user.branch_id
                request.active_branch = user.branch

        token = set_current_branch(branch_id)
        try:
            return self.get_response(request)
        finally:
            reset_current_branch(token)

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
