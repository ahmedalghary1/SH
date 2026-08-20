from datetime import date, datetime

from django.test import SimpleTestCase

from audit.templatetags.arabic_dates import arabic_date, arabic_datetime
from config.date_ranges import resolve_date_period


class InvoiceDatePeriodTests(SimpleTestCase):
    def test_current_week_starts_saturday_and_ends_friday(self):
        selected = resolve_date_period({'period': 'this_week'}, today=date(2026, 8, 20))

        self.assertEqual(selected['date_from'], date(2026, 8, 15))
        self.assertEqual(selected['date_to'], date(2026, 8, 21))

    def test_previous_week_is_previous_saturday_to_friday(self):
        selected = resolve_date_period({'period': 'last_week'}, today=date(2026, 8, 20))

        self.assertEqual(selected['date_from'], date(2026, 8, 8))
        self.assertEqual(selected['date_to'], date(2026, 8, 14))

    def test_custom_dates_are_normalized_when_entered_backwards(self):
        selected = resolve_date_period({
            'period': 'custom',
            'date_from': '2026-08-20',
            'date_to': '2026-08-10',
        })

        self.assertEqual(selected['date_from'], date(2026, 8, 10))
        self.assertEqual(selected['date_to'], date(2026, 8, 20))

    def test_custom_period_accepts_date_and_time_boundaries(self):
        selected = resolve_date_period({
            'period': 'custom',
            'datetime_from': '2026-08-20T09:15',
            'datetime_to': '2026-08-20T18:45',
        })

        self.assertEqual(selected['datetime_from_value'], '2026-08-20T09:15')
        self.assertEqual(selected['datetime_to_value'], '2026-08-20T18:45')

    def test_arabic_date_filters_use_arabic_names_and_digits(self):
        self.assertEqual(arabic_date(date(2026, 8, 20)), 'الخميس، ٢٠ أغسطس ٢٠٢٦')
        self.assertIn('١١:٠٥ ص', arabic_datetime(datetime(2026, 8, 20, 11, 5)))
