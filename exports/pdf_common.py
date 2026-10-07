"""Shared ReportLab setup: fonts (with ₹ glyph), colours, paragraph styles, helpers."""
from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, Table, TableStyle

from core.config import ROOT_DIR

FONT_DIR = ROOT_DIR / "assets" / "fonts"
_registered = False

NAVY = colors.HexColor("#0B3C5D")
ORANGE = colors.HexColor("#E8710A")
LIGHT = colors.HexColor("#F4F6FA")
LINE = colors.HexColor("#D9DEE7")
INK = colors.HexColor("#1F2937")
MUTED = colors.HexColor("#6B7280")
GREEN = colors.HexColor("#15803D")
AMBER = colors.HexColor("#B45309")
RED = colors.HexColor("#B91C1C")

STANCE_COLORS = {"Positive": GREEN, "Neutral": AMBER, "Cautious": RED}


def register_fonts() -> None:
    global _registered
    if _registered:
        return
    files = {
        "DV": "DejaVuSans.ttf",
        "DV-Bold": "DejaVuSans-Bold.ttf",
        "DVC": "DejaVuSansCondensed.ttf",
        "DVC-Bold": "DejaVuSansCondensed-Bold.ttf",
    }
    for name, fn in files.items():
        path = Path(FONT_DIR) / fn
        pdfmetrics.registerFont(TTFont(name, str(path)))
    pdfmetrics.registerFontFamily("DV", normal="DV", bold="DV-Bold", italic="DV", boldItalic="DV-Bold")
    pdfmetrics.registerFontFamily("DVC", normal="DVC", bold="DVC-Bold", italic="DVC", boldItalic="DVC-Bold")
    _registered = True


def styles() -> dict[str, ParagraphStyle]:
    register_fonts()
    base = ParagraphStyle("base", fontName="DV", fontSize=8.6, leading=12, textColor=INK)
    return {
        "base": base,
        "small": ParagraphStyle("small", parent=base, fontSize=7, leading=9, textColor=MUTED),
        "tiny": ParagraphStyle("tiny", parent=base, fontSize=6.3, leading=8, textColor=MUTED),
        "title": ParagraphStyle("title", parent=base, fontName="DV-Bold", fontSize=20, leading=24, textColor=NAVY),
        "subtitle": ParagraphStyle("subtitle", parent=base, fontSize=9, textColor=MUTED),
        "h1": ParagraphStyle("h1", parent=base, fontName="DV-Bold", fontSize=13, leading=17, textColor=NAVY,
                             spaceBefore=6, spaceAfter=4),
        "h2": ParagraphStyle("h2", parent=base, fontName="DV-Bold", fontSize=10.5, leading=14, textColor=ORANGE,
                             spaceBefore=8, spaceAfter=3),
        "h3": ParagraphStyle("h3", parent=base, fontName="DV-Bold", fontSize=8.6, leading=11, textColor=NAVY,
                             spaceBefore=4, spaceAfter=2),
        "banner": ParagraphStyle("banner", parent=base, fontName="DV-Bold", fontSize=11, leading=15,
                                 textColor=colors.white),
        "body": ParagraphStyle("body", parent=base, alignment=4, spaceAfter=5),  # justified
        "bullet": ParagraphStyle("bullet", parent=base, leftIndent=10, bulletIndent=0, spaceAfter=2),
        "cell": ParagraphStyle("cell", parent=base, fontName="DVC", fontSize=7, leading=8.6),
        "cell_b": ParagraphStyle("cell_b", parent=base, fontName="DVC-Bold", fontSize=7, leading=8.6),
        "cell_r": ParagraphStyle("cell_r", parent=base, fontName="DVC", fontSize=7, leading=8.6, alignment=TA_RIGHT),
        "cell_hdr": ParagraphStyle("cell_hdr", parent=base, fontName="DVC-Bold", fontSize=7, leading=8.6,
                                   textColor=colors.white, alignment=TA_RIGHT),
        "cell_hdr_l": ParagraphStyle("cell_hdr_l", parent=base, fontName="DVC-Bold", fontSize=7, leading=8.6,
                                     textColor=colors.white, alignment=TA_LEFT),
        "link": ParagraphStyle("link", parent=base, fontSize=7.6, leading=10, textColor=colors.HexColor("#1D4ED8")),
    }


def esc(text) -> str:
    return escape(str(text if text is not None else ""))


def data_table(columns: list[str], rows: list[dict], width: float, first_col: float, st: dict,
               header_bg=ORANGE, font_size: float = 7.0, zebra: bool = True) -> Table:
    """rows: [{'metric','values', 'bold'?, 'indent'?}] -> styled Table."""
    n = len(columns)
    other = (width - first_col) / max(n, 1)
    cell_r = ParagraphStyle("r", parent=st["cell_r"], fontSize=font_size, leading=font_size + 1.6)
    cell_l = ParagraphStyle("l", parent=st["cell"], fontSize=font_size, leading=font_size + 1.6)
    cell_lb = ParagraphStyle("lb", parent=st["cell_b"], fontSize=font_size, leading=font_size + 1.6)
    hdr_r = ParagraphStyle("hr", parent=st["cell_hdr"], fontSize=font_size, leading=font_size + 1.6)
    hdr_l = ParagraphStyle("hl", parent=st["cell_hdr_l"], fontSize=font_size, leading=font_size + 1.6)
    data = [[Paragraph("", hdr_l)] + [Paragraph(esc(c), hdr_r) for c in columns]]
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), header_bg),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]
    for i, r in enumerate(rows, start=1):
        label = ("&nbsp;&nbsp;&nbsp;" if r.get("indent") else "") + esc(r["metric"])
        lstyle = cell_lb if r.get("bold") else cell_l
        if r.get("indent"):
            label = f"<font color='#6B7280'>{label}</font>"
        vals = list(r["values"]) + [""] * (n - len(r["values"]))
        data.append([Paragraph(label, lstyle)] + [Paragraph(esc(v) if v != "" else "–", cell_r) for v in vals[:n]])
        if r.get("bold"):
            style.append(("FONTNAME", (0, i), (-1, i), "DVC-Bold"))
        if zebra and i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), LIGHT))
    t = Table(data, colWidths=[first_col] + [other] * n, repeatRows=1)
    t.setStyle(TableStyle(style))
    return t


def kv_table(rows: list[list[str]], width: float, st: dict, label_ratio: float = 0.55,
             header: str | None = None) -> Table:
    data = []
    style = [
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 1.6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    if header:
        data.append([Paragraph(f"<b>{esc(header)}</b>", ParagraphStyle("kh", parent=st["cell_b"], textColor=NAVY,
                                                                        fontSize=8)), ""])
        style += [("SPAN", (0, 0), (-1, 0)), ("LINEBELOW", (0, 0), (-1, 0), 1, NAVY)]
    for k, v in rows:
        data.append([Paragraph(esc(k), st["cell"]), Paragraph(esc(v), st["cell_r"])])
    t = Table(data, colWidths=[width * label_ratio, width * (1 - label_ratio)])
    t.setStyle(TableStyle(style))
    return t
