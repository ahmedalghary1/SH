from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


FONT_NAME = 'Helvetica'


def _register_font():
    global FONT_NAME
    candidates = [
        Path('C:/Windows/Fonts/tahoma.ttf'),
        Path('C:/Windows/Fonts/arial.ttf'),
        settings.BASE_DIR / 'static' / 'fonts' / 'Cairo-Regular.ttf',
    ]
    for path in candidates:
        if path.exists():
            font_name = path.stem.replace('-', '')
            pdfmetrics.registerFont(TTFont(font_name, str(path)))
            FONT_NAME = font_name
            return


def _p(value, style):
    return Paragraph(str(value or '-'), style)


def build_invoice_report_pdf(*, invoices, company_settings):
    _register_font()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title='Invoice Report',
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'ArabicTitle',
        parent=styles['Title'],
        fontName=FONT_NAME,
        fontSize=16,
        leading=22,
        alignment=TA_RIGHT,
        spaceAfter=6,
    )
    meta_style = ParagraphStyle(
        'ArabicMeta',
        parent=styles['Normal'],
        fontName=FONT_NAME,
        fontSize=9,
        leading=13,
        alignment=TA_RIGHT,
        textColor=colors.HexColor('#475569'),
    )
    cell_style = ParagraphStyle(
        'ArabicCell',
        parent=styles['Normal'],
        fontName=FONT_NAME,
        fontSize=8,
        leading=11,
        alignment=TA_RIGHT,
    )
    header_style = ParagraphStyle(
        'ArabicHeader',
        parent=cell_style,
        fontSize=8.5,
        textColor=colors.white,
    )

    invoice_list = list(invoices)
    story = [
        Paragraph(company_settings.company_name or 'شركة الملابس', title_style),
        Paragraph('تقرير الفواتير', title_style),
        Paragraph(f'تاريخ التصدير: {timezone.localtime().strftime("%Y-%m-%d %H:%M")}', meta_style),
        Paragraph(f'عدد الفواتير: {len(invoice_list)}', meta_style),
        Spacer(1, 8),
    ]

    rows = [[
        _p('التاريخ', header_style),
        _p('المتبقي', header_style),
        _p('المدفوع', header_style),
        _p('الإجمالي', header_style),
        _p('الدفع', header_style),
        _p('المندوب', header_style),
        _p('العميل', header_style),
        _p('رقم الطلب', header_style),
        _p('رقم الفاتورة', header_style),
    ]]

    for invoice in invoice_list:
        order = invoice.order
        rows.append([
            _p(timezone.localtime(invoice.issued_at).strftime('%Y-%m-%d'), cell_style),
            _p(order.remaining_amount, cell_style),
            _p(order.paid_amount, cell_style),
            _p(order.total, cell_style),
            _p(order.get_payment_method_display(), cell_style),
            _p(order.created_by or '-', cell_style),
            _p(order.customer or 'عميل فردي', cell_style),
            _p(order.order_number, cell_style),
            _p(invoice.invoice_number, cell_style),
        ])

    if len(rows) == 1:
        rows.append([_p('لا توجد فواتير مطابقة', cell_style)] + [''] * 8)

    table = Table(
        rows,
        repeatRows=1,
        colWidths=[28 * mm, 24 * mm, 24 * mm, 24 * mm, 32 * mm, 30 * mm, 44 * mm, 35 * mm, 35 * mm],
    )
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#071D35')),
        ('GRID', (0, 0), (-1, -1), .25, colors.HexColor('#DDE5EE')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(table)

    doc.build(story)
    return buffer.getvalue()
