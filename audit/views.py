from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Q
from django.shortcuts import render

from accounts.permissions import ManagerRequiredMixin
from .models import AuditLog


@staff_member_required
def audit_log_list(request):
    """View for managers to view audit logs with filtering."""
    if not request.user.is_manager and not request.user.is_superuser:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden('غير مصرح لك بالوصول إلى هذه الصفحة')
    
    queryset = AuditLog.objects.select_related('user').order_by('-created_at')
    
    # Filtering
    user_filter = request.GET.get('user')
    section_filter = request.GET.get('section')
    action_filter = request.GET.get('action')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    search = request.GET.get('q')
    
    if user_filter:
        queryset = queryset.filter(user_id=user_filter)
    if section_filter:
        queryset = queryset.filter(section=section_filter)
    if action_filter:
        queryset = queryset.filter(action=action_filter)
    if date_from:
        queryset = queryset.filter(created_at__date__gte=date_from)
    if date_to:
        queryset = queryset.filter(created_at__date__lte=date_to)
    if search:
        queryset = queryset.filter(
            Q(model_name__icontains=search) |
            Q(object_id__icontains=search) |
            Q(object_repr__icontains=search) |
            Q(notes__icontains=search)
        )
    
    # Get filter options
    users = AuditLog.objects.values_list('user__username', 'user__id').distinct()
    sections = AuditLog.SECTION_CHOICES
    actions = AuditLog.ACTION_CHOICES
    
    context = {
        'logs': queryset[:500],  # Limit to 500 for performance
        'users': users,
        'sections': sections,
        'actions': actions,
        'filters': {
            'user': user_filter,
            'section': section_filter,
            'action': action_filter,
            'date_from': date_from,
            'date_to': date_to,
            'q': search,
        },
    }
    
    return render(request, 'audit/audit_log_list.html', context)
