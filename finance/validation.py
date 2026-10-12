"""Validate numbers before they reach database fields or query parameters."""

from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.core.validators import DecimalValidator
from django.utils.dateparse import parse_date as django_parse_date


def decimal_value(value, *, max_digits=None, decimal_places=2):
    try:
        parsed = Decimal(str(value if value not in (None, '') else 0))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError('القيمة الرقمية غير صحيحة') from None
    if not parsed.is_finite():
        raise ValidationError('القيمة الرقمية غير صحيحة')
    if max_digits is not None:
        DecimalValidator(max_digits, decimal_places)(parsed)
    return parsed


def validate_money_fields(instance, *names):
    """Check stored money limits while allowing calculated fractions to round."""
    for name in names:
        field = instance._meta.get_field(name)
        value = decimal_value(getattr(instance, name))
        if abs(value) >= Decimal(10) ** (field.max_digits - field.decimal_places):
            raise ValidationError('قيمة المبلغ تتجاوز الحد المسموح')


def integer_value(value, *, minimum=1, maximum=2147483647):
    parsed = decimal_value(value)
    if parsed != parsed.to_integral_value() or not minimum <= parsed <= maximum:
        raise ValidationError('الكمية يجب أن تكون عددًا صحيحًا ضمن النطاق المسموح')
    return int(parsed)


def positive_id(value):
    """Return a safe database id, including for malicious oversized input."""
    text = str(value or '').strip()
    if not text.isascii() or not text.isdigit() or len(text) > 19:
        return None
    parsed = int(text)
    return parsed if 0 < parsed <= 9223372036854775807 else None


def filter_id(queryset, field, value):
    if value in (None, ''):
        return queryset
    parsed = positive_id(value)
    return queryset.filter(**{field: parsed}) if parsed is not None else queryset.none()


def report_days(value, default=90):
    try:
        return integer_value(value, maximum=36500)
    except ValidationError:
        return default


def parse_date(value):
    try:
        return django_parse_date(value or '')
    except (TypeError, ValueError, OverflowError):
        return None
