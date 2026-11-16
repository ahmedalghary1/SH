"""
Log Sanitization Utility
=========================
Removes or masks sensitive data before it appears in logs.

Usage:
    from config.log_sanitizer import sanitize, SanitizingFilter

    # Sanitize a dict
    safe = sanitize({'username': 'ali', 'password': 'secret123'})
    # → {'username': 'ali', 'password': '***REDACTED***'}

    # Sanitize a string (masks values next to sensitive keys)
    safe = sanitize("token=abc123&user=ali")
    # → "token=***REDACTED***&user=ali"

    # Add as a logging Filter to auto-sanitize all log records
    handler.addFilter(SanitizingFilter())
"""
import logging
import re
from typing import Any

# ------------------------------------------------------------------ #
#  Sensitive field names (case-insensitive)                           #
# ------------------------------------------------------------------ #
_SENSITIVE_KEYS = frozenset({
    'password', 'passwd', 'pass',
    'token', 'access_token', 'refresh_token', 'id_token', 'auth_token',
    'secret', 'client_secret',
    'authorization', 'x-authorization',
    'cookie', 'set-cookie',
    'card', 'card_number', 'cardnumber', 'pan',
    'cvv', 'cvc', 'cvc2', 'cvv2',
    'expiry', 'expiration', 'card_expiry',
    'national_id', 'national_number', 'ssn', 'nid',
    'phone', 'mobile', 'phone_number',
    'credit', 'debit',
    'private_key', 'api_key', 'apikey',
    'pin',
})

_REDACTED = '***REDACTED***'

# Regex for key=value patterns in strings (URL-encoded or plain)
# Matches:  key=value  or  "key": "value"  or  'key': 'value'
_KV_PATTERN = re.compile(
    r'(?i)'
    r'('
    + '|'.join(re.escape(k) for k in sorted(_SENSITIVE_KEYS, key=len, reverse=True))
    + r')'
    r'(\s*[=:]\s*[\'""]?)'   # = or : with optional quotes
    r'([^\s&,\'"";}\]]+)',    # value (up to whitespace / delimiter)
    re.IGNORECASE,
)


def sanitize(data: Any) -> Any:
    """
    Recursively sanitize sensitive fields.

    - dict  → sensitive keys replaced with _REDACTED
    - list  → each element sanitized recursively
    - str   → key=value patterns masked
    - other → returned as-is
    """
    if isinstance(data, dict):
        return {
            k: (_REDACTED if _is_sensitive_key(k) else sanitize(v))
            for k, v in data.items()
        }
    if isinstance(data, (list, tuple)):
        sanitized = [sanitize(item) for item in data]
        return type(data)(sanitized)
    if isinstance(data, str):
        return _sanitize_string(data)
    return data


def _is_sensitive_key(key: str) -> bool:
    """Return True if the key name matches a sensitive field."""
    return str(key).lower().strip() in _SENSITIVE_KEYS


def _sanitize_string(text: str) -> str:
    """Mask sensitive key=value pairs inside a string."""
    return _KV_PATTERN.sub(lambda m: f'{m.group(1)}{m.group(2)}{_REDACTED}', text)


def sanitize_error_text(text):
    """Redact configured secrets even when an exception omits their key names."""
    from django.conf import settings

    text = _sanitize_string(str(text))
    if settings.configured:
        secrets = [getattr(settings, name, '') for name in (
            'SECRET_KEY', 'EMAIL_HOST_PASSWORD', 'BACKUP_ENCRYPTION_KEY',
        )]
        secrets.extend(db.get('PASSWORD', '') for db in settings.DATABASES.values())
        for secret in sorted({str(s) for s in secrets if s and len(str(s)) >= 4}, key=len, reverse=True):
            text = text.replace(secret, _REDACTED)
            if ' ' in secret and len(secret.replace(' ', '')) >= 8:
                text = text.replace(secret.replace(' ', ''), _REDACTED)
    return text


class SanitizingFormatter(logging.Formatter):
    def formatException(self, exc_info):
        return sanitize_error_text(super().formatException(exc_info))

    def format(self, record):
        return sanitize_error_text(super().format(record))


# ------------------------------------------------------------------ #
#  Logging Filter                                                     #
# ------------------------------------------------------------------ #

class SanitizingFilter(logging.Filter):
    """
    A logging.Filter that sanitizes log record messages and args.

    Add to any handler or logger:
        handler.addFilter(SanitizingFilter())
    """

    def filter(self, record: logging.LogRecord) -> bool:
        from config.request_context import request_id
        context_id = request_id.get()
        reference = getattr(record, 'request_id', '-')
        if not reference or reference == '-':
            reference = getattr(getattr(record, 'request', None), 'request_id', '-')
        record.request_id = context_id if context_id != '-' else reference
        # Sanitize the formatted message
        if isinstance(record.msg, str):
            record.msg = _sanitize_string(record.msg)
        elif isinstance(record.msg, dict):
            record.msg = sanitize(record.msg)

        # Sanitize args passed to % formatting
        if record.args:
            if isinstance(record.args, dict):
                record.args = sanitize(record.args)
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    _sanitize_string(a) if isinstance(a, str) else a
                    for a in record.args
                )

        return True  # Always allow the record through (we only sanitize)
