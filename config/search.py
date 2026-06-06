import re
from itertools import product

from django.db.models import Q


_DIACRITICS_RE = re.compile(r'[\u064b-\u065f\u0670\u0640]')
_CHAR_GROUPS = {
    'ا': ('ا', 'أ', 'إ', 'آ', 'ٱ'),
    'ي': ('ي', 'ى', 'ئ'),
    'و': ('و', 'ؤ'),
    'ه': ('ه', 'ة'),
}


def normalize_arabic(value):
    text = str(value or '').strip().lower()
    text = _DIACRITICS_RE.sub('', text)
    replacements = {
        'أ': 'ا',
        'إ': 'ا',
        'آ': 'ا',
        'ٱ': 'ا',
        'ى': 'ي',
        'ئ': 'ي',
        'ؤ': 'و',
        'ة': 'ه',
        'ء': '',
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return ' '.join(text.split())


def arabic_search_terms(value, max_terms=80):
    original = str(value or '').strip()
    normalized = normalize_arabic(original)
    if not normalized:
        return []

    chars = []
    for char in normalized:
        chars.append(_CHAR_GROUPS.get(char, (char,)))

    terms = {original, normalized}
    for combo in product(*chars):
        terms.add(''.join(combo))
        if len(terms) >= max_terms:
            break
    return [term for term in terms if term]


def arabic_search_q(fields, value):
    query = Q()
    for term in arabic_search_terms(value):
        for field in fields:
            query |= Q(**{f'{field}__icontains': term})
    return query


def matches_arabic_search(values, value):
    needle = normalize_arabic(value)
    if not needle:
        return True
    return any(needle in normalize_arabic(candidate) for candidate in values)
