from pathlib import Path

from django.conf import settings
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
except ImportError:  # pragma: no cover - kept as a safe fallback before deps are installed.
    arabic_reshaper = None
    get_display = None


FONT_NAME = 'Helvetica'


def register_arabic_font():
    global FONT_NAME
    candidates = [
        Path('C:/Windows/Fonts/tahoma.ttf'),
        Path('C:/Windows/Fonts/arial.ttf'),
        settings.BASE_DIR / 'static' / 'fonts' / 'Cairo-Regular.ttf',
    ]
    for path in candidates:
        if path.exists():
            font_name = path.stem.replace('-', '')
            if font_name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(font_name, str(path)))
            FONT_NAME = font_name
            return FONT_NAME
    return FONT_NAME


def shape_arabic(value):
    text = str(value if value not in (None, '') else '-')
    if arabic_reshaper and get_display:
        return get_display(arabic_reshaper.reshape(text))
    return text


def arabic_paragraph(value, style):
    return Paragraph(shape_arabic(value), style)
