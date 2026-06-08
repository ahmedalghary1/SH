from django.core.cache import cache
from django.http import JsonResponse


class RateLimitExceeded(Exception):
    pass


def get_client_ip(request):
    """Get client IP address from request."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def rate_limit(request, key_prefix, max_requests=60, period=60):
    """
    Simple rate limiting using Django cache.
    
    Args:
        request: The HTTP request object
        key_prefix: Prefix for the cache key (e.g., 'login', 'search')
        max_requests: Maximum number of requests allowed
        period: Time period in seconds
    
    Returns:
        bool: True if under limit, False if exceeded
    
    Raises:
        RateLimitExceeded: If rate limit is exceeded
    """
    ip = get_client_ip(request)
    cache_key = f'ratelimit:{key_prefix}:{ip}'
    
    # Get current count
    count = cache.get(cache_key, 0)
    
    if count >= max_requests:
        raise RateLimitExceeded()
    
    # Increment count
    cache.set(cache_key, count + 1, period)
    
    return True


def rate_limit_decorator(key_prefix, max_requests=60, period=60):
    """
    Decorator for rate limiting view functions.
    
    Args:
        key_prefix: Prefix for the cache key
        max_requests: Maximum number of requests allowed
        period: Time period in seconds
    """
    def decorator(view_func):
        def wrapped_view(request, *args, **kwargs):
            try:
                rate_limit(request, key_prefix, max_requests, period)
                return view_func(request, *args, **kwargs)
            except RateLimitExceeded:
                return JsonResponse(
                    {
                        'success': False,
                        'message': 'تجاوزت الحد المسموح من الطلبات. يرجى المحاولة مرة أخرى بعد دقيقة.',
                    },
                    status=429
                )
        return wrapped_view
    return decorator
