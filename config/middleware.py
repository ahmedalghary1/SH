from uuid import uuid4

from .request_context import request_id


class RequestIdMiddleware:
    """Tie a user-visible error reference to its server traceback."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = uuid4().hex[:16]
        token = request_id.set(request.request_id)
        try:
            response = self.get_response(request)
            response['X-Request-ID'] = request.request_id
            return response
        finally:
            request_id.reset(token)
