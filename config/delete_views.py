from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models.deletion import ProtectedError, RestrictedError
from django.shortcuts import redirect
from django.views.generic import DeleteView

from accounts.permissions import ManagerRequiredMixin, can_hard_delete


class ManagerDeleteView(ManagerRequiredMixin, DeleteView):
    template_name = 'partials/confirm_delete.html'
    success_message = 'تم الحذف بنجاح'
    protected_message = 'لا يمكن حذف هذا السجل لأنه مرتبط ببيانات أخرى في النظام. يمكنك تعطيله أو إلغاء العملية المرتبطة به بدل الحذف.'

    def dispatch(self, request, *args, **kwargs):
        if not can_hard_delete(request.user):
            raise PermissionDenied('ليس لديك صلاحية الحذف النهائي')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault('title', 'تأكيد الحذف')
        context.setdefault('cancel_url', self.get_success_url())
        return context

    def form_valid(self, form):
        success_url = self.get_success_url()
        try:
            response = super().form_valid(form)
        except (ProtectedError, RestrictedError):
            messages.error(self.request, self.protected_message)
            return redirect(success_url)
        messages.success(self.request, self.success_message)
        return response
