from django.test import RequestFactory, SimpleTestCase, override_settings

from config.pwa import manifest_view, service_worker_view


@override_settings(ALLOWED_HOSTS=['erp.example', 'localhost'])
class PwaMetadataTests(SimpleTestCase):
    def test_manifest_keeps_identity_and_declares_itself_for_desktop_detection(self):
        import json

        for origin in ['https://erp.example', 'http://localhost:8000']:
            request = RequestFactory().get('/manifest.json', HTTP_HOST=origin.split('//')[1],
                                           secure=origin.startswith('https:'))
            response = manifest_view(request)
            manifest = json.loads(response.content)
            self.assertEqual(manifest['id'], '/')
            self.assertEqual(manifest['start_url'], '/')
            self.assertEqual(manifest['scope'], '/')
            self.assertEqual(manifest['display'], 'standalone')
            self.assertEqual(manifest['related_applications'], [{
                'platform': 'webapp', 'id': origin + '/', 'url': origin + '/manifest.json',
            }])
            self.assertFalse(manifest['prefer_related_applications'])
            self.assertEqual(response['Content-Type'], 'application/manifest+json')

    def test_worker_remains_root_scoped_and_revalidated(self):
        response = service_worker_view(RequestFactory().get('/service-worker.js'))
        try:
            self.assertEqual(response['Service-Worker-Allowed'], '/')
            self.assertIn('no-store', response['Cache-Control'])
            self.assertEqual(response['Content-Type'], 'application/javascript')
        finally:
            response.close()
