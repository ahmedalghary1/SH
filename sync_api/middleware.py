from django.http import HttpResponse


class SyncApiCorsMiddleware:
    """Allow the Electron file:// renderer to call the sync API."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith('/api/'):
            if request.method == 'OPTIONS':
                response = HttpResponse(status=204)
            else:
                response = self.get_response(request)
            response['Access-Control-Allow-Origin'] = '*'
            response['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
            response['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
            response['Access-Control-Max-Age'] = '86400'
            return response
        return self.get_response(request)
