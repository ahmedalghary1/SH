from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import LoginView, LogoutView
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView, UpdateView, View

from config.delete_views import ManagerDeleteView
from config.exports import ExportListMixin
from config.ratelimit import RateLimitExceeded, rate_limit
from config.security_logger import log_failed_login

from .forms import ArabicAuthenticationForm, UserCreateForm, UserUpdateForm
from .models import User
from .permissions import ManagerRequiredMixin


def ensure_sales_rep_cash_account(user):
    if user.role == User.ROLE_SALES:
        from finance.models import CashAccount
        CashAccount.get_for_user(user)


# Keep the login POST tolerant of stale/missing CSRF cookies caused by old
# cached auth pages or misconfigured deployment proxies. Other POST endpoints
# remain protected by CsrfViewMiddleware.
@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(ensure_csrf_cookie, name='dispatch')
@method_decorator(never_cache, name='dispatch')
class AppLoginView(LoginView):
    template_name = 'accounts/login.html'
    authentication_form = ArabicAuthenticationForm
    redirect_authenticated_user = True
    
    def dispatch(self, request, *args, **kwargs):
        try:
            rate_limit(request, 'login', max_requests=10, period=60)
        except RateLimitExceeded:
            log_failed_login(request, reason='rate_limit_exceeded')
            messages.error(request, 'تجاوزت الحد المسموح من محاولات تسجيل الدخول. يرجى المحاولة مرة أخرى بعد دقيقة.')
            return redirect(self.get_success_url())
        return super().dispatch(request, *args, **kwargs)

    def form_invalid(self, form):
        """Log failed authentication attempts."""
        log_failed_login(self.request, reason='invalid_credentials')
        return super().form_invalid(form)

    def form_valid(self, form):
        response = super().form_valid(form)
        self.request.session.set_expiry(settings.SESSION_COOKIE_AGE)
        self.request.session.modified = True
        return response


class AppLogoutView(LogoutView):
    pass


class UserListView(ManagerRequiredMixin, ExportListMixin, ListView):
    model = User
    template_name = 'accounts/users/list.html'
    context_object_name = 'users'
    paginate_by = 20
    export_title = 'قائمة المستخدمين'
    export_filename = 'users'
    export_columns = (
        ('اسم المستخدم', 'username'),
        ('الدور', 'get_role_display'),
        ('الهاتف', 'phone'),
        ('الحالة', lambda user: 'نشط' if user.is_active else 'متوقف'),
        ('تاريخ الإضافة', 'created_at'),
    )

    def get_queryset(self):
        return User.objects.order_by('-created_at')


class UserCreateView(ManagerRequiredMixin, CreateView):
    model = User
    form_class = UserCreateForm
    template_name = 'accounts/users/create.html'
    success_url = reverse_lazy('accounts:user_list')

    def form_valid(self, form):
        response = super().form_valid(form)
        ensure_sales_rep_cash_account(self.object)
        messages.success(self.request, 'تم إنشاء الموظف بنجاح')
        return response


class UserUpdateView(ManagerRequiredMixin, UpdateView):
    model = User
    form_class = UserUpdateForm
    template_name = 'accounts/users/update.html'
    success_url = reverse_lazy('accounts:user_list')

    def form_valid(self, form):
        response = super().form_valid(form)
        ensure_sales_rep_cash_account(self.object)
        messages.success(self.request, 'تم تحديث بيانات الموظف')
        return response


class UserDeactivateView(ManagerRequiredMixin, View):
    def post(self, request, pk):
        user = User.objects.get(pk=pk)
        if user == request.user:
            messages.error(request, 'لا يمكنك تعطيل حسابك الحالي')
        else:
            user.is_active = False
            user.save(update_fields=['is_active'])
            messages.success(request, 'تم تعطيل الموظف')
        return redirect('accounts:user_list')


class UserDeleteView(ManagerDeleteView):
    model = User
    success_url = reverse_lazy('accounts:user_list')
    success_message = 'تم حذف الموظف'

    def form_valid(self, form):
        if self.get_object() == self.request.user:
            messages.error(self.request, 'لا يمكنك حذف حسابك الحالي')
            return redirect(self.success_url)
        return super().form_valid(form)

# Create your views here.
