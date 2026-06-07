from django.test import SimpleTestCase
from django.urls import NoReverseMatch, reverse


class RetiredReportRoutesTests(SimpleTestCase):
    def test_report_routes_are_not_registered(self):
        with self.assertRaises(NoReverseMatch):
            reverse('reports:sales')
