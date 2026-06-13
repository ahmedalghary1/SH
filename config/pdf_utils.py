from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
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


def _font_candidates():
    configured_path = getattr(settings, 'PDF_ARABIC_FONT_PATH', '')
    candidates = []
    if configured_path:
        candidates.append(Path(configured_path).expanduser())
    candidates.extend([
        settings.BASE_DIR / 'static' / 'fonts' / 'NotoNaskhArabic-Regular.ttf',
        settings.BASE_DIR / 'static' / 'fonts' / 'Cairo-Regular.ttf',
        settings.BASE_DIR / 'static' / 'fonts' / 'Amiri-Regular.ttf',
        Path('/home/elwsamst/fonts/NotoNaskhArabic-Regular.ttf'),
        Path('/home/elwsamst/fonts/Cairo-Regular.ttf'),
        Path('/home/elwsamst/public_html/fonts/NotoNaskhArabic-Regular.ttf'),
        Path('/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf'),
        Path('/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf'),
        Path('/usr/share/fonts/opentype/noto/NotoNaskhArabic-Regular.ttf'),
        Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
        Path('/usr/share/fonts/truetype/freefont/FreeSans.ttf'),
        Path('/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf'),
        Path('C:/Windows/Fonts/tahoma.ttf'),
        Path('C:/Windows/Fonts/arial.ttf'),
    ])
    return candidates


def _font_supports_arabic(path):
    try:
        probe = TTFont(f'{path.stem}Probe', str(path))
    except Exception:
        return False
    char_to_glyph = getattr(probe.face, 'charToGlyph', {})
    return any(0x0600 <= codepoint <= 0x06FF for codepoint in char_to_glyph)


def register_arabic_font():
    global FONT_NAME
    for path in _font_candidates():
        if not path.exists() or not _font_supports_arabic(path):
            continue
        font_name = path.stem.replace('-', '')
        if font_name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(font_name, str(path)))
        FONT_NAME = font_name
        return FONT_NAME
    raise ImproperlyConfigured(
        'No Arabic-capable TrueType font was found for PDF export. '
        'Add static/fonts/NotoNaskhArabic-Regular.ttf or set PDF_ARABIC_FONT_PATH.'
    )


def shape_arabic(value):
    text = str(value if value not in (None, '') else '-')
    if arabic_reshaper and get_display:
        return get_display(arabic_reshaper.reshape(text))
    return text


def arabic_paragraph(value, style):
    return Paragraph(shape_arabic(value), style)
