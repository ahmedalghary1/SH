from django.contrib import messages
from django.contrib.auth.views import LoginView, LogoutView
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView, UpdateView, View

from config.exports import ExportListMixin
from config.ratelimit import RateLimitExceeded, rate_limit
from config.security_logger import log_failed_login

from .forms import ArabicAuthenticationForm, UserCreateForm, UserUpdateForm
from .models import User
from .permissions import ManagerRequiredMixin


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
        ('الاسم الأول', 'first_name'),
        ('الاسم الأخير', 'last_name'),
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
        messages.success(self.request, 'تم إنشاء الموظف بنجاح')
        return super().form_valid(form)


class UserUpdateView(ManagerRequiredMixin, UpdateView):
    model = User
    form_class = UserUpdateForm
    template_name = 'accounts/users/update.html'
    success_url = reverse_lazy('accounts:user_list')

    def form_valid(self, form):
        messages.success(self.request, 'تم تحديث بيانات الموظف')
        return super().form_valid(form)


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

# Create your views here.
