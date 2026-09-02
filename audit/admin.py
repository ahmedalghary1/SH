from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['created_at', 'user', 'get_action_display', 'get_section_display', 'model_name', 'object_repr']
    list_filter = ['branch', 'action', 'section', 'created_at', 'user']
    search_fields = ['user__username', 'user__email', 'model_name', 'object_id', 'object_repr', 'notes']
    readonly_fields = ['created_at', 'user', 'action', 'section', 'model_name', 'object_id', 'object_repr', 
                      'changes_before', 'changes_after', 'ip_address', 'user_agent', 'notes']
    date_hierarchy = 'created_at'
    ordering = ['-created_at']
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
