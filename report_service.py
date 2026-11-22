"""Генерація PDF-звіту про витрати одного ЦН за місяць."""
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import io
import os
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle


_FONT_NAME = "CoHBotDejaVu"
_FONT_BOLD_NAME = "CoHBotDejaVuBold"
_FONT_CANDIDATES = (
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
)


def _register_unicode_fonts():
    registered = set(pdfmetrics.getRegisteredFontNames())
    if _FONT_NAME not in registered or _FONT_BOLD_NAME not in registered:
        for regular_path, bold_path in _FONT_CANDIDATES:
            if os.path.isfile(regular_path) and os.path.isfile(bold_path):
                if _FONT_NAME not in registered:
                    pdfmetrics.registerFont(TTFont(_FONT_NAME, regular_path))
                if _FONT_BOLD_NAME not in registered:
                    pdfmetrics.registerFont(TTFont(_FONT_BOLD_NAME, bold_path))
                break
        else:
            raise RuntimeError("Не знайдено DejaVu Sans для коректного відображення українського тексту в PDF")
    pdfmetrics.registerFontFamily(
        _FONT_NAME,
        normal=_FONT_NAME,
        bold=_FONT_BOLD_NAME,
        italic=_FONT_NAME,
        boldItalic=_FONT_BOLD_NAME,
    )


def _money(value) -> Decimal:
    try:
        result = Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Некоректна сума витрати")
    if not result.is_finite():
        raise ValueError("Некоректна сума витрати")
    return result


def _format_money(value) -> str:
    amount = _money(value)
    whole, fractional = f"{amount:,.2f}".split(".")
    return f"{whole.replace(',', ' ')},{fractional} грн"


def _month_label(month: str) -> str:
    try:
        parsed = datetime.strptime(month, "%Y-%m")
    except (TypeError, ValueError):
        raise ValueError("Місяць має бути у форматі YYYY-MM")
    months = (
        "січень", "лютий", "березень", "квітень", "травень", "червень",
        "липень", "серпень", "вересень", "жовтень", "листопад", "грудень",
    )
    return f"{months[parsed.month - 1]} {parsed.year}"


def summarize_expenses(expenses: list) -> tuple[list, Decimal, dict]:
    """Нормалізує рядки та рахує загальну суму й підсумки за категоріями."""
    rows = []
    categories = defaultdict(lambda: Decimal("0.00"))
    total = Decimal("0.00")
    for source in expenses or []:
        row = dict(source)
        amount = _money(row.get("amount"))
        category = str(row.get("category_name") or "Інше")
        row["_amount_decimal"] = amount
        rows.append(row)
        total += amount
        categories[category] += amount
    return rows, total, dict(categories)


def build_monthly_expense_pdf(report: dict) -> bytes:
    """Повертає готовий PDF; зображення чеків до звіту не додаються."""
    if not isinstance(report, dict) or not report.get("center_id"):
        raise ValueError("У звіті мають бути дані Центру Надії")
    center_name = str(report.get("center_name") or "").strip()
    if not center_name:
        raise ValueError("Не вказано назву Центру Надії")
    month = str(report.get("month") or "")
    period_label = _month_label(month)
    expenses, total, by_category = summarize_expenses(report.get("expenses") or [])

    _register_unicode_fonts()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.4 * cm,
        leftMargin=1.4 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        title=f"Звіт витрат — {center_name} — {period_label}",
        author="Облік Витрат",
    )
    base = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle", parent=base["Title"], fontName=_FONT_BOLD_NAME,
        fontSize=17, leading=22, alignment=TA_CENTER, spaceAfter=8,
    )
    subtitle_style = ParagraphStyle(
        "ReportSubtitle", parent=base["Normal"], fontName=_FONT_NAME,
        fontSize=10, leading=14, alignment=TA_CENTER, textColor=colors.HexColor("#4b5563"),
        spaceAfter=14,
    )
    heading_style = ParagraphStyle(
        "ReportHeading", parent=base["Heading2"], fontName=_FONT_BOLD_NAME,
        fontSize=12, leading=16, spaceBefore=9, spaceAfter=6,
    )
    cell_style = ParagraphStyle(
        "ReportCell", parent=base["Normal"], fontName=_FONT_NAME,
        fontSize=8.5, leading=11, alignment=TA_LEFT,
    )
    header_style = ParagraphStyle(
        "ReportTableHeader", parent=cell_style, fontName=_FONT_BOLD_NAME,
        textColor=colors.white,
    )
    amount_style = ParagraphStyle(
        "ReportAmount", parent=cell_style, alignment=TA_RIGHT,
    )
    story = [
        Paragraph("Звіт витрат", title_style),
        Paragraph(f"{escape(center_name)} · {escape(period_label)}", subtitle_style),
        Paragraph(
            f"Кількість витрат: {len(expenses)}<br/>Загальна сума: "
            f"<b>{_format_money(total)}</b>",
            cell_style,
        ),
        Spacer(1, 0.25 * cm),
    ]

    story.append(Paragraph("Підсумки за категоріями", heading_style))
    category_rows = [[
        Paragraph("Категорія", header_style),
        Paragraph("Сума", header_style),
    ]]
    for category, amount in sorted(by_category.items(), key=lambda item: (-item[1], item[0].casefold())):
        category_rows.append([
            Paragraph(escape(category), cell_style),
            Paragraph(escape(_format_money(amount)), amount_style),
        ])
    if not by_category:
        category_rows.append([Paragraph("Витрат за цей період немає", cell_style), ""])
    category_table = LongTable(category_rows, colWidths=[12.5 * cm, 4.0 * cm], repeatRows=1)
    category_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f6b5c")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 1), (1, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.extend([category_table, Spacer(1, 0.25 * cm), Paragraph("Витрати за період", heading_style)])

    expense_rows = [[
        Paragraph("Дата", header_style),
        Paragraph("Назва", header_style),
        Paragraph("Категорія", header_style),
        Paragraph("Сума", header_style),
    ]]
    for row in expenses:
        try:
            date_label = datetime.strptime(str(row.get("date"))[:10], "%Y-%m-%d").strftime("%d.%m.%Y")
        except ValueError:
            date_label = str(row.get("date") or "")[:10]
        expense_rows.append([
            Paragraph(escape(date_label), cell_style),
            Paragraph(escape(str(row.get("expense_name") or "")), cell_style),
            Paragraph(escape(str(row.get("category_name") or "Інше")), cell_style),
            Paragraph(escape(_format_money(row["_amount_decimal"])), amount_style),
        ])
    if not expenses:
        expense_rows.append([Paragraph("Витрат за цей період немає", cell_style), "", "", ""])
    expense_table = LongTable(
        expense_rows,
        colWidths=[2.3 * cm, 7.1 * cm, 5.1 * cm, 2.0 * cm],
        repeatRows=1,
    )
    expense_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f6b5c")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (-1, 1), (-1, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(expense_table)
    doc.build(story)
    return buffer.getvalue()
