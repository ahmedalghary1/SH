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
