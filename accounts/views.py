from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import LoginView, LogoutView
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView, UpdateView, View
from django.utils.http import url_has_allowed_host_and_scheme

from config.delete_views import ManagerDeleteView
from config.exports import ExportListMixin
from config.ratelimit import RateLimitExceeded, rate_limit
from config.security_logger import log_failed_login

from .forms import ArabicAuthenticationForm, BranchForm, UserCreateForm, UserUpdateForm
from .models import Branch, User
from .permissions import ManagerRequiredMixin, SuperuserRequiredMixin


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
        qs = User.objects.order_by('-created_at')
        if self.request.user.is_superuser:
            return qs.filter(branch=self.request.active_branch) if self.request.active_branch else qs
        return qs.filter(branch=self.request.user.branch)


class UserCreateView(ManagerRequiredMixin, CreateView):
    model = User
    form_class = UserCreateForm
    template_name = 'accounts/users/create.html'
    success_url = reverse_lazy('accounts:user_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['actor'] = self.request.user
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, 'تم إنشاء الموظف بنجاح')
        return response


class UserUpdateView(ManagerRequiredMixin, UpdateView):
    model = User
    form_class = UserUpdateForm
    template_name = 'accounts/users/update.html'
    success_url = reverse_lazy('accounts:user_list')

    def get_queryset(self):
        qs = User.objects.all()
        return qs if self.request.user.is_superuser else qs.filter(branch=self.request.user.branch)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['actor'] = self.request.user
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, 'تم تحديث بيانات الموظف')
        return response


class UserDeactivateView(ManagerRequiredMixin, View):
    def post(self, request, pk):
        qs = User.objects.all() if request.user.is_superuser else User.objects.filter(branch=request.user.branch)
        user = get_object_or_404(qs, pk=pk)
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

    def get_queryset(self):
        qs = User.objects.all()
        return qs if self.request.user.is_superuser else qs.filter(branch=self.request.user.branch)
    success_message = 'تم حذف الموظف'

    def form_valid(self, form):
        if self.get_object() == self.request.user:
            messages.error(self.request, 'لا يمكنك حذف حسابك الحالي')
            return redirect(self.success_url)
        return super().form_valid(form)

class BranchListView(SuperuserRequiredMixin, ListView):
    model = Branch
    template_name = 'accounts/branches/list.html'
    context_object_name = 'branches'


class BranchCreateView(SuperuserRequiredMixin, CreateView):
    model = Branch
    form_class = BranchForm
    template_name = 'accounts/branches/form.html'
    success_url = reverse_lazy('accounts:branch_list')


class BranchUpdateView(SuperuserRequiredMixin, UpdateView):
    model = Branch
    form_class = BranchForm
    template_name = 'accounts/branches/form.html'
    success_url = reverse_lazy('accounts:branch_list')


class BranchSelectView(SuperuserRequiredMixin, View):
    def post(self, request):
        branch_id = request.POST.get('branch')
        if branch_id:
            branch = get_object_or_404(Branch, pk=branch_id, is_active=True)
            request.session['active_branch_id'] = branch.pk
        else:
            request.session.pop('active_branch_id', None)
        next_url = request.POST.get('next') or ''
        if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
            next_url = '/'
        return redirect(next_url)


# Create your views here.
