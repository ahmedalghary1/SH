import json

from django.db import IntegrityError, transaction
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
                if selected and str(selected).isascii() and str(selected).isdecimal() and len(str(selected)) <= 18:
                    from .models import Branch
                    request.active_branch = Branch.objects.filter(pk=selected, is_active=True).first()
                    branch_id = request.active_branch.pk if request.active_branch else None
                elif selected:
                    request.session.pop(self.SESSION_KEY, None)
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
        if not token or not request.user.is_authenticated:
            return self.get_response(request)
        if len(token) > 64:
            return JsonResponse({'success': False, 'message': 'رمز الحفظ غير صالح. أعد تحميل الصفحة.'}, status=400)
        # Reserve the token and commit the business operation together. A failed
        # write must never leave a receipt that blocks the user's next retry.
        with transaction.atomic():
            try:
                with transaction.atomic():
                    SubmissionReceipt.objects.create(token=token, user=request.user, path=request.path[:255])
            except IntegrityError:
                return JsonResponse({'success': False, 'duplicate': True, 'message': 'تم استلام هذا الطلب من قبل ولن يتم تكرار الحفظ.'}, status=409)
            response = self.get_response(request)
            if response.status_code >= 400:
                transaction.set_rollback(True)
            elif response.status_code == 200:
                # A bound HTML form indicates failed validation, not a save.
                context = getattr(response, 'context_data', None) or {}
                form = context.get('form')
                failed_validation = bool(form is not None and form.is_bound and form.errors)
                if response.get('Content-Type', '').startswith('application/json'):
                    try:
                        failed_validation = json.loads(response.content).get('success') is False
                    except (ValueError, AttributeError):
                        pass
                if failed_validation:
                    transaction.set_rollback(True)
            return response
