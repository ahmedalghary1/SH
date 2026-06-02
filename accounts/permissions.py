from functools import wraps

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied


def has_role(user, *roles):
    if not user.is_authenticated:
        return False
    if user.is_superuser or getattr(user, 'role', None) == 'manager':
        return True
    return getattr(user, 'role', None) in roles


def role_required(*roles):
    def decorator(view_func):
        @login_required
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if has_role(request.user, *roles):
                return view_func(request, *args, **kwargs)
            raise PermissionDenied
        return wrapper
    return decorator


manager_required = role_required('manager')
sales_required = role_required('manager', 'sales')
warehouse_required = role_required('manager', 'warehouse')


class RoleRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    allowed_roles = ()

    def test_func(self):
        return has_role(self.request.user, *self.allowed_roles)


class ManagerRequiredMixin(RoleRequiredMixin):
    allowed_roles = ('manager',)


class SalesRequiredMixin(RoleRequiredMixin):
    allowed_roles = ('manager', 'sales')


class WarehouseRequiredMixin(RoleRequiredMixin):
    allowed_roles = ('manager', 'warehouse')
