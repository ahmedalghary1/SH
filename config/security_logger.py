"""
Security Logger
===============
Centralised helpers for logging security-relevant events to the 'security' logger.

The 'security' logger is configured in settings.py to write to logs/security.log
in production and to console in development.

IMPORTANT: Never pass raw passwords, tokens, or sensitive values to these functions.
           All messages are additionally passed through SanitizingFilter in the handler.

Usage:
    from config.security_logger import (
        log_failed_login,
        log_permission_denied,
        log_suspicious_request,
        log_failed_sensitive_op,
        log_audit_error,
    )
"""
import logging

logger = logging.getLogger('security')


def _ip(request) -> str:
    """Extract client IP from request without leaking sensitive headers."""
    if not request:
        return 'unknown'
    xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', 'unknown')


def _username(request) -> str:
    """Safe username extraction — never returns a password."""
    if not request:
        return 'anonymous'
    user = getattr(request, 'user', None)
    if user and getattr(user, 'is_authenticated', False):
        return getattr(user, 'username', 'authenticated')
    # Check POST for attempted username (login page) — do NOT include password
    attempted = request.POST.get('username', '')
    if attempted:
        # Trim and mask excessively long values (potential injection)
        return attempted[:64] if len(attempted) <= 64 else attempted[:64] + '...'
    return 'anonymous'


# ------------------------------------------------------------------ #
#  Public API                                                         #
# ------------------------------------------------------------------ #

def log_failed_login(request, reason: str = ''):
    """
    Log a failed login attempt.

    Args:
        request: The HTTP request object.
        reason:  Human-readable reason (e.g. 'invalid credentials', 'rate limit').
    """
    ip = _ip(request)
    username = _username(request)
    msg = f'FAILED_LOGIN | ip={ip} | user={username}'
    if reason:
        msg += f' | reason={reason}'
    logger.warning(msg)


def log_permission_denied(request, resource: str = ''):
    """
    Log a permission-denied event.

    Args:
        request:  The HTTP request object.
        resource: The URL or resource path that was denied.
    """
    ip = _ip(request)
    username = _username(request)
    path = resource or (request.path if request else 'unknown')
    logger.warning(
        f'PERMISSION_DENIED | ip={ip} | user={username} | resource={path}'
    )


def log_suspicious_request(request, detail: str = ''):
    """
    Log a request that looks suspicious (e.g. rate-limit hit, malformed input).

    Args:
        request: The HTTP request object.
        detail:  Short description of what looks suspicious.
    """
    ip = _ip(request)
    username = _username(request)
    path = request.path if request else 'unknown'
    method = request.method if request else 'unknown'
    msg = f'SUSPICIOUS_REQUEST | ip={ip} | user={username} | method={method} | path={path}'
    if detail:
        msg += f' | detail={detail}'
    logger.warning(msg)


def log_failed_sensitive_op(request, operation: str, reason: str = ''):
    """
    Log a failed sensitive operation (payment, export, privilege change, etc.).

    Args:
        request:   The HTTP request object (can be None for management commands).
        operation: Short label for the operation (e.g. 'export_financial_data').
        reason:    What went wrong.
    """
    ip = _ip(request)
    username = _username(request)
    msg = f'FAILED_SENSITIVE_OP | ip={ip} | user={username} | op={operation}'
    if reason:
        msg += f' | reason={reason}'
    logger.error(msg)


def log_audit_error(request, detail: str = '', exc: Exception = None):
    """
    Log a failure in the audit logging subsystem itself.

    Args:
        request: The HTTP request object (can be None).
        detail:  What was being audited when the error occurred.
        exc:     The exception that was caught (logged without traceback to avoid loops).
    """
    ip = _ip(request)
    username = _username(request)
    msg = f'AUDIT_ERROR | ip={ip} | user={username}'
    if detail:
        msg += f' | detail={detail}'
    if exc:
        msg += f' | exception={type(exc).__name__}: {str(exc)[:200]}'
    logger.error(msg)
