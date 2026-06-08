from audit.models import AuditLog


def log_audit(
    *,
    user,
    action,
    section,
    model_name=None,
    object_id=None,
    object_repr=None,
    changes_before=None,
    changes_after=None,
    ip_address=None,
    user_agent=None,
    notes=None,
):
    """
    Log an audit event for sensitive operations.
    
    Args:
        user: The user who performed the action
        action: One of AuditLog.ACTION_* constants
        section: One of AuditLog.SECTION_* constants
        model_name: Name of the model being affected
        object_id: ID of the object being affected
        object_repr: String representation of the object
        changes_before: Dict of field values before the change
        changes_after: Dict of field values after the change
        ip_address: IP address of the user
        user_agent: User agent string
        notes: Additional notes about the action
    """
    AuditLog.objects.create(
        user=user,
        action=action,
        section=section,
        model_name=model_name,
        object_id=str(object_id) if object_id else None,
        object_repr=object_repr,
        changes_before=changes_before,
        changes_after=changes_after,
        ip_address=ip_address,
        user_agent=user_agent,
        notes=notes,
    )


def get_client_info(request):
    """
    Extract IP address and user agent from request.
    
    Returns:
        tuple: (ip_address, user_agent)
    """
    ip_address = None
    user_agent = None
    
    if request:
        # Get IP address from request
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip_address = x_forwarded_for.split(',')[0].strip()
        else:
            ip_address = request.META.get('REMOTE_ADDR')
        
        # Get user agent
        user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]  # Limit length
    
    return ip_address, user_agent


def log_audit_with_request(request, **kwargs):
    """
    Log an audit event with IP address and user agent extracted from request.
    
    Args:
        request: The HTTP request object
        **kwargs: Arguments to pass to log_audit
    """
    ip_address, user_agent = get_client_info(request)
    return log_audit(ip_address=ip_address, user_agent=user_agent, **kwargs)
