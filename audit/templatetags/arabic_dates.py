from datetime import date, datetime

from django import template
from django.utils import timezone


register = template.Library()

ARABIC_MONTHS = (
    '', 'يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو',
    'يوليو', 'أغسطس', 'سبتمبر', 'أكتوبر', 'نوفمبر', 'ديسمبر',
)
ARABIC_DAYS = (
    'الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس',
    'الجمعة', 'السبت', 'الأحد',
)
ARABIC_DIGITS = str.maketrans('0123456789', '٠١٢٣٤٥٦٧٨٩')


def _digits(value):
    return str(value).translate(ARABIC_DIGITS)


@register.filter
def arabic_date(value):
    if not isinstance(value, (date, datetime)):
        return value or '-'
    if isinstance(value, datetime) and timezone.is_aware(value):
        value = timezone.localtime(value)
    return f'{ARABIC_DAYS[value.weekday()]}، {_digits(value.day)} {ARABIC_MONTHS[value.month]} {_digits(value.year)}'


@register.filter
def arabic_datetime(value):
    if not isinstance(value, datetime):
        return arabic_date(value)
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    hour = value.hour % 12 or 12
    marker = 'ص' if value.hour < 12 else 'م'
    return f'{arabic_date(value)}، {_digits(hour)}:{_digits(f"{value.minute:02d}")} {marker}'


@register.filter
def arabic_time(value):
    if not value:
        return '-'
    hour = value.hour % 12 or 12
    marker = 'ص' if value.hour < 12 else 'م'
    return f'{_digits(hour)}:{_digits(f"{value.minute:02d}")} {marker}'
