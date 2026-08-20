from datetime import datetime, time, timedelta

from django.utils import timezone
from django.db.models import Q
from django.utils.dateparse import parse_date, parse_datetime


PERIOD_CHOICES = (
    ('today', 'اليوم'),
    ('yesterday', 'الأمس'),
    ('this_week', 'الأسبوع الحالي'),
    ('last_week', 'الأسبوع السابق'),
    ('this_month', 'الشهر الحالي'),
    ('last_month', 'الشهر السابق'),
    ('this_year', 'العام الحالي'),
    ('last_year', 'العام السابق'),
    ('custom', 'فترة مخصصة'),
)


def _month_bounds(year, month):
    start = datetime(year, month, 1).date()
    if month == 12:
        next_month = datetime(year + 1, 1, 1).date()
    else:
        next_month = datetime(year, month + 1, 1).date()
    return start, next_month - timedelta(days=1)


def resolve_date_period(params, today=None):
    """Return the selected date bounds; weeks always run Saturday-Friday."""
    today = today or timezone.localdate()
    period = (params.get('period') or '').strip()
    date_from = parse_date(params.get('date_from', ''))
    date_to = parse_date(params.get('date_to', ''))
    datetime_from = parse_datetime(params.get('datetime_from', ''))
    datetime_to = parse_datetime(params.get('datetime_to', ''))

    if datetime_from and timezone.is_naive(datetime_from):
        datetime_from = timezone.make_aware(datetime_from, timezone.get_current_timezone())
    if datetime_to and timezone.is_naive(datetime_to):
        datetime_to = timezone.make_aware(datetime_to, timezone.get_current_timezone())

    if not period and (date_from or date_to or datetime_from or datetime_to):
        period = 'custom'

    if period == 'today':
        date_from = date_to = today
    elif period == 'yesterday':
        date_from = date_to = today - timedelta(days=1)
    elif period in {'this_week', 'last_week'}:
        # Python weekday: Monday=0 ... Saturday=5.
        days_since_saturday = (today.weekday() - 5) % 7
        date_from = today - timedelta(days=days_since_saturday)
        if period == 'last_week':
            date_from -= timedelta(days=7)
        date_to = date_from + timedelta(days=6)
    elif period == 'this_month':
        date_from, date_to = _month_bounds(today.year, today.month)
    elif period == 'last_month':
        previous_month_end = today.replace(day=1) - timedelta(days=1)
        date_from, date_to = _month_bounds(previous_month_end.year, previous_month_end.month)
    elif period == 'this_year':
        date_from = today.replace(month=1, day=1)
        date_to = today.replace(month=12, day=31)
    elif period == 'last_year':
        date_from = today.replace(year=today.year - 1, month=1, day=1)
        date_to = today.replace(year=today.year - 1, month=12, day=31)

    if date_from and date_to and date_to < date_from:
        date_from, date_to = date_to, date_from

    if period == 'custom':
        if not datetime_from and date_from:
            datetime_from = timezone.make_aware(datetime.combine(date_from, time.min), timezone.get_current_timezone())
        if not datetime_to and date_to:
            datetime_to = timezone.make_aware(datetime.combine(date_to, time.max), timezone.get_current_timezone())
        if datetime_from:
            date_from = timezone.localtime(datetime_from).date()
        if datetime_to:
            date_to = timezone.localtime(datetime_to).date()
    else:
        if date_from:
            datetime_from = timezone.make_aware(datetime.combine(date_from, time.min), timezone.get_current_timezone())
        if date_to:
            datetime_to = timezone.make_aware(datetime.combine(date_to, time.max), timezone.get_current_timezone())

    if datetime_from and datetime_to and datetime_to < datetime_from:
        datetime_from, datetime_to = datetime_to, datetime_from
        date_from, date_to = datetime_from.date(), datetime_to.date()
    return {
        'period': period,
        'date_from': date_from,
        'date_to': date_to,
        'date_from_value': date_from.isoformat() if date_from else '',
        'date_to_value': date_to.isoformat() if date_to else '',
        'datetime_from': datetime_from,
        'datetime_to': datetime_to,
        'datetime_from_value': timezone.localtime(datetime_from).strftime('%Y-%m-%dT%H:%M') if datetime_from else '',
        'datetime_to_value': timezone.localtime(datetime_to).strftime('%Y-%m-%dT%H:%M') if datetime_to else '',
    }


def filter_by_date_period(queryset, params, field_name, today=None):
    selected = resolve_date_period(params, today=today)
    if field_name.endswith('__date'):
        datetime_field = field_name[:-6]
        if selected['datetime_from']:
            queryset = queryset.filter(**{f'{datetime_field}__gte': selected['datetime_from']})
        if selected['datetime_to']:
            queryset = queryset.filter(**{f'{datetime_field}__lte': selected['datetime_to']})
    else:
        if selected['date_from']:
            queryset = queryset.filter(**{f'{field_name}__gte': selected['date_from']})
        if selected['date_to']:
            queryset = queryset.filter(**{f'{field_name}__lte': selected['date_to']})
    return queryset, selected


def filter_by_split_datetime(queryset, params, date_field, time_field, today=None):
    """Filter models that store the transaction date and time in separate fields."""
    selected = resolve_date_period(params, today=today)
    if selected['datetime_from']:
        lower = timezone.localtime(selected['datetime_from'])
        queryset = queryset.filter(
            Q(**{f'{date_field}__gt': lower.date()})
            | Q(**{date_field: lower.date(), f'{time_field}__gte': lower.time()})
        )
    if selected['datetime_to']:
        upper = timezone.localtime(selected['datetime_to'])
        queryset = queryset.filter(
            Q(**{f'{date_field}__lt': upper.date()})
            | Q(**{date_field: upper.date(), f'{time_field}__lte': upper.time()})
        )
    return queryset, selected
