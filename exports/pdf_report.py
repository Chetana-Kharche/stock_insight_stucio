"""Broker-style PDF for an analysis report (layout inspired by Indian brokerage company updates)."""
from __future__ import annotations

import io
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Frame, FrameBreak, Image, KeepTogether,
                                NextPageTemplate, PageTemplate, Paragraph, Spacer, Table, TableStyle)

from core.config import APP_NAME
from core.units import CRORE_HELP, unit_of
from analysis.forecast import reader_text
from core.config import get_settings
from exports import charts
from exports.pdf_common import (LIGHT, LINE, MUTED, NAVY, ORANGE, STANCE_COLORS, data_table, esc, kv_table,
                                register_fonts, styles)

PAGE_W, PAGE_H = A4
M = 1.3 * cm
CONTENT_W = PAGE_W - 2 * M


def _fmt_date(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).strftime("%d %B %Y")
    except ValueError:
        return str(iso)[:10]


def _header_footer(report: dict):
    comp = report.get("company", {})
    name = comp.get("name") or ""

    def draw(canvas, doc):
        canvas.saveState()
        # header
        canvas.setFillColor(NAVY)
        canvas.setFont("DV-Bold", 9)
        canvas.drawString(M, PAGE_H - 0.9 * cm, f"{name} | Company Analysis | {_fmt_date(report.get('generated_at'))}")
        canvas.setFillColor(ORANGE)
        canvas.setFont("DV-Bold", 10)
        canvas.drawRightString(PAGE_W - M, PAGE_H - 0.9 * cm, APP_NAME)
        canvas.setStrokeColor(ORANGE)
        canvas.setLineWidth(1.4)
        canvas.line(M, PAGE_H - 1.1 * cm, PAGE_W - M, PAGE_H - 1.1 * cm)
        # footer
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.5)
        canvas.line(M, 1.25 * cm, PAGE_W - M, 1.25 * cm)
        canvas.setFont("DV", 6.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(M, 0.85 * cm, "AI-assisted analysis from public data. Not investment advice. "
                                        "See disclaimer at the end of this report.")
        canvas.drawRightString(PAGE_W - M, 0.85 * cm, f"Page {doc.page}")
        canvas.restoreState()

    return draw


def _img(png: bytes | None, width: float):
    if not png:
        return None
    img = Image(io.BytesIO(png))
    ratio = img.imageHeight / float(img.imageWidth)
    img.drawWidth = width
    img.drawHeight = width * ratio
    return img


def _unit(unit, st: dict):
    """Small green 'Unit: ₹ crore' line printed above a chart or table.

    unit is a string, or a (unit, detail) pair from core.units.unit_of().
    """
    detail = ""
    if isinstance(unit, (tuple, list)):
        unit, detail = unit[0], (unit[1] if len(unit) > 1 else "")
    if not unit:
        return None
    html = f"<font color='#15803D'><b>Unit: {esc(unit)}</b></font>"
    if detail:
        html += f" <font color='#6B7280'>· {esc(detail)}</font>"
    return Paragraph(html, st["unit"])


def _exhibit_parts(n: int, title: str, chart: dict | None, width: float, st: dict,
                   source: str = "Screener.in") -> list:
    """Title, unit line, image and source line of one chart exhibit (empty list if there is no chart)."""
    if not chart:
        return []
    img = _img(chart.get("png"), width)
    if img is None:
        return []
    return [x for x in [
        Paragraph(f"<font color='#E8710A'><b>Exhibit {n}:</b></font> <b>{esc(title)}</b>", st["h3"]),
        _unit(chart.get("unit", ""), st),
        img,
        Paragraph(f"Source: {esc(source)}, {APP_NAME}", st["tiny"]),
        Spacer(1, 6),
    ] if x is not None]


def _exhibit(n: int, title: str, chart: dict | None, width: float, st: dict, source: str = "Screener.in"):
    """chart = {'png': bytes, 'unit': str} from exports.charts."""
    parts = _exhibit_parts(n, title, chart, width, st, source)
    return KeepTogether(parts) if parts else None


def _table_exhibit(n: int, title: str, unit: str, table, st: dict, note: str = ""):
    items = [Paragraph(f"<font color='#E8710A'><b>Exhibit {n}:</b></font> <b>{esc(title)}</b>", st["h3"]),
             _unit(unit, st), table]
    if note:
        items.append(Paragraph(esc(note), st["tiny"]))
    items.append(Spacer(1, 8))
    return KeepTogether([x for x in items if x is not None])


def _link_table(header: list[str], rows: list[list], widths: list[float], st: dict) -> Table:
    """Table whose cells are ready-made Paragraph markup (used for rows that contain links)."""
    data = [[Paragraph(f"<b>{esc(h)}</b>", st["cell_hdr_l"]) for h in header]]
    data += [[Paragraph(c, st["cell"]) for c in r] for r in rows]
    t = Table(data, colWidths=widths, repeatRows=1)
    style = [("BACKGROUND", (0, 0), (-1, 0), NAVY), ("LINEBELOW", (0, 1), (-1, -1), 0.25, LINE),
             ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 2.5),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5), ("LEFTPADDING", (0, 0), (-1, -1), 3),
             ("RIGHTPADDING", (0, 0), (-1, -1), 3)]
    for i in range(2, len(data), 2):
        style.append(("BACKGROUND", (0, i), (-1, i), LIGHT))
    t.setStyle(TableStyle(style))
    return t


def _a(url: str, text: str) -> str:
    return f"<link href='{esc(url)}'><font color='#1D4ED8'>{esc(text)}</font></link>"


def build_report_pdf(report: dict, payload: dict | None = None) -> bytes:
    register_fonts()
    st = styles()
    st["unit"] = ParagraphStyle("unit", parent=st["base"], fontSize=7, leading=9, spaceBefore=0, spaceAfter=2)
    buf = io.BytesIO()
    comp = report.get("company", {})
    stance = report.get("stance", "Neutral")
    stance_col = STANCE_COLORS.get(stance, NAVY)

    # ---------------- page templates
    top_h = 6.3 * cm
    top_y = PAGE_H - 1.35 * cm - top_h
    side_w = 6.0 * cm
    gap = 0.5 * cm
    main_w = CONTENT_W - side_w - gap
    body_top = top_y - 0.2 * cm
    body_h = body_top - 1.5 * cm
    first = PageTemplate(id="first", frames=[
        Frame(M, top_y, CONTENT_W, top_h, id="top", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0),
        Frame(M + main_w + gap, 1.5 * cm, side_w, body_h, id="side", leftPadding=6, rightPadding=0, topPadding=0,
              bottomPadding=0, showBoundary=0),
        Frame(M, 1.5 * cm, main_w, body_h, id="main", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0),
    ], onPage=_header_footer(report))
    later = PageTemplate(id="later", frames=[
        Frame(M, 1.5 * cm, CONTENT_W, PAGE_H - 1.5 * cm - 1.4 * cm, id="full", leftPadding=0, rightPadding=0,
              topPadding=0, bottomPadding=0)
    ], onPage=_header_footer(report))
    doc = BaseDocTemplate(buf, pagesize=A4, leftMargin=M, rightMargin=M, topMargin=1.4 * cm, bottomMargin=1.5 * cm,
                          title=f"{comp.get('name', '')} - Company Analysis", author=APP_NAME,
                          pageTemplates=[first, later])

    story: list = [NextPageTemplate("later")]

    # ---------------- top block
    md = dict(report.get("market_data") or [])
    stance_tbl = Table([[
        Paragraph(f"<font color='white'><b>{esc(stance.upper())}</b></font>",
                  st["banner"]),
        Paragraph(f"<b>Score:</b> {report.get('score', 0):.0f}/100", st["base"]),
        Paragraph(f"<b>CMP:</b> ₹{esc(md.get('CMP (₹)', '–'))}", st["base"]),
        Paragraph(f"<b>Mkt Cap:</b> ₹{esc(md.get('Market Cap (₹ Cr)', '–'))} Cr", st["base"]),
    ]], colWidths=[3.3 * cm, 3.6 * cm, 4.2 * cm, CONTENT_W - 11.1 * cm])
    stance_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), stance_col),
        ("BACKGROUND", (1, 0), (-1, 0), LIGHT),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story += [
        Spacer(1, 4), stance_tbl, Spacer(1, 6),
        Table([[Paragraph(f"<b>{esc(_fmt_date(report.get('generated_at')))}</b>",
                          ParagraphStyle("d", parent=st["base"], textColor=ORANGE)),
                Paragraph("<b>India | AI-assisted Equity Analysis</b>",
                          ParagraphStyle("d2", parent=st["base"], textColor=ORANGE, alignment=2))]],
              colWidths=[CONTENT_W / 2, CONTENT_W / 2],
              style=[("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]),
        Paragraph(esc(comp.get("name", "")), st["title"]),
        Paragraph(esc(" · ".join(x for x in [comp.get("broad_industry"), comp.get("industry")] if x)
                      or comp.get("sector") or ""), st["subtitle"]),
        Spacer(1, 5),
    ]
    banner = Table([[Paragraph(esc(report.get("headline", "")), st["banner"])]], colWidths=[CONTENT_W])
    banner.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NAVY), ("TOPPADDING", (0, 0), (-1, -1), 6),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 6), ("LEFTPADDING", (0, 0), (-1, -1), 8)]))
    story += [banner, FrameBreak()]

    # ---------------- sidebar
    story.append(kv_table(report.get("market_data") or [], side_w - 6, st, header="Market Data"))
    story.append(Spacer(1, 8))
    if report.get("price_performance"):
        story.append(kv_table(report["price_performance"], side_w - 6, st, header="Price Performance (% change)"))
        story.append(Spacer(1, 8))
    sh = report.get("shareholding_table") or {}
    if sh.get("rows"):
        cols = sh["columns"][-3:]
        rows = [[r["metric"], " / ".join(r["values"][-3:])] for r in sh["rows"]]
        story.append(kv_table(rows, side_w - 6, st, label_ratio=0.38,
                              header=f"Shareholding, % of shares ({' / '.join(cols)})"))
        story.append(Spacer(1, 8))
    sc_rows = [[f"{it['name']} ({it['weight']}%)", f"{it['score']:.1f}/10"] for it in report.get("scorecard", [])]
    sc_rows.append(["Overall score", f"{report.get('score', 0):.0f}/100 · {stance}"])
    story.append(kv_table(sc_rows, side_w - 6, st, header="Scorecard (score out of 10)"))
    story.append(Spacer(1, 6))
    story.append(Paragraph("Stance scale: Positive ≥ 65, Neutral 45–65, Cautious &lt; 45. "
                           "Mechanical score; not a price target.", st["tiny"]))
    story.append(FrameBreak())

    # ---------------- main column (page 1) then continues full width
    from analysis import guardrails as G

    if report.get("quality_checks"):
        story.append(Paragraph(f"<font color='#12783C'><b>✔ {esc(G.reader_badge(report))}</b></font>", st["tiny"]))
    summary_box = Table([[Paragraph(esc(report.get("executive_summary", "")), st["body"])]], colWidths=[main_w])
    summary_box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), LIGHT), ("LEFTPADDING", (0, 0), (-1, -1), 8),
                                     ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 6),
                                     ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                                     ("LINEBEFORE", (0, 0), (0, -1), 2.5, ORANGE)]))
    story += [summary_box, Spacer(1, 6)]
    notes = G.reader_notes(report)
    if notes:
        story.append(Paragraph("<font color='#B45309'><b>Data notes</b></font>", st["small"]))
        story += [Paragraph(esc(n), st["small"], bulletText="•") for n in notes]
        story.append(Spacer(1, 4))
    if report.get("investment_thesis"):
        story.append(Paragraph("Investment thesis", st["h2"]))
        for b in report["investment_thesis"]:
            story.append(Paragraph(esc(b), st["bullet"], bulletText="•"))
    if report.get("stance_rationale"):
        story.append(Paragraph(f"Why {esc(stance)}?", st["h2"]))
        story.append(Paragraph(esc(report["stance_rationale"]), st["body"]))

    # ---------------- narrative sections
    for sec in report.get("sections", []):
        story.append(Paragraph(esc(sec.get("heading", "")), st["h2"]))
        for para in str(sec.get("body", "")).split("\n"):
            if para.strip():
                story.append(Paragraph(esc(para.strip()), st["body"]))

    # ---------------- exhibits
    ex = 1
    chart_w = CONTENT_W * 0.92
    exhibits = []
    half = (3.75, 2.55)                      # chart size for two-per-row (fonts stay readable)
    if payload:
        exhibits = [
            ("Share price with 50/200-day moving averages", charts.price_chart(payload.get("price_history") or [], half), 1),
            ("Annual revenue and net profit", charts.annual_revenue_profit(payload, half), 1),
            ("Quarterly trend", charts.quarterly_trend(payload), 2),
            ("Margins and return ratios", charts.margins_returns(payload, half), 1),
            ("Valuation: trailing P/E vs 5-year median", charts.pe_chart(payload.get("pe_history") or {}, half), 1),
            ("Shareholding pattern", charts.shareholding_trend(payload, half), 1),
        ]
    exhibits = [(t, c, w) for t, c, w in exhibits if c]
    if exhibits:
        head = [Paragraph("Exhibits", st["h1"]),
                Paragraph("The green line above each chart gives the unit of the numbers. " + CRORE_HELP + ".",
                          st["small"]), Spacer(1, 3)]
        # two charts per row (wide ones take the full row); each row is one block, so a row moves to the next page
        # only if it does not fit - no half-empty pages after the text
        col_w = (CONTENT_W - 0.4 * cm) / 2
        rows, pending = [], []
        for title, chart, span in exhibits:
            if span == 2:
                if pending:
                    rows.append(pending)
                    pending = []
                rows.append([(ex, title, chart, CONTENT_W * 0.92)])
            else:
                pending.append((ex, title, chart, col_w))
                if len(pending) == 2:
                    rows.append(pending)
                    pending = []
            ex += 1
        if pending:
            rows.append(pending)
        for i, row in enumerate(rows):
            cells = [_exhibit_parts(n, t, c, w, st) for n, t, c, w in row]
            if len(row) == 1 and row[0][3] > col_w:
                block = _exhibit(*row[0][:4], st)
            else:
                while len(cells) < 2:
                    cells.append([Spacer(1, 1)])
                block = Table([cells], colWidths=[col_w + 0.2 * cm, col_w + 0.2 * cm])
                block.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                           ("RIGHTPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 0),
                                           ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
            story.append(KeepTogether(head + [block]) if i == 0 else block)

    # ---------------- model projections
    fc = report.get("forecast") or {}
    if fc.get("ok"):
        ft = fc.get("tables") or {}
        story += [CondPageBreak(9 * cm), Paragraph("Future outlook: model projections", st["h1"]),
                  Paragraph(esc(reader_text(fc)), st["body"])]
        story.append(_exhibit(ex, "Past results and estimates for the next three years",
                              charts.forecast_chart(fc), CONTENT_W, st,
                              source="Screener.in history; estimates"))
        ex += 1
        for key, title, unit_key, first in (("annual", "Projection by fiscal year (E = estimate by the model)",
                                             "forecast_annual", 5.4 * cm),
                                            ("quarterly", "Projection for the next four quarters",
                                             "forecast_quarterly", 5.4 * cm)):
            t = ft.get(key) or {}
            if t.get("rows"):
                story.append(_table_exhibit(ex, title, unit_of(unit_key),
                                            data_table(t["columns"], t["rows"], CONTENT_W, first, st, header_bg=NAVY),
                                            st, "Base case = most likely value; low and high case = likely range."))
                ex += 1
        tfi = fc.get("timesfm") or {}
        if tfi.get("used"):
            for key, title, unit_key in (("timesfm_annual", "TimesFM AI forecast (Google Research) by fiscal year",
                                          "forecast_annual"),
                                         ("timesfm_quarterly", "TimesFM AI forecast for the next four quarters",
                                          "forecast_quarterly")):
                t = ft.get(key) or {}
                if t.get("rows"):
                    story.append(_table_exhibit(ex, title, unit_of(unit_key),
                                                data_table(t["columns"], t["rows"], CONTENT_W, 5.4 * cm, st,
                                                           header_bg=NAVY),
                                                st, "A second, independent AI estimate shown for comparison with the base case above."))
                    ex += 1
        elif tfi:
            story.append(Paragraph(esc(f"TimesFM AI forecast: not used for this report. {tfi.get('reason') or ''}"),
                                   st["small"]))
        t = ft.get("derived") or {}
        if t.get("rows"):
            story.append(_table_exhibit(ex, "What the projection implies", ("times (x) and %", "first row in times, second row in percent"),
                                        data_table(t["columns"], t["rows"], CONTENT_W, 8.4 * cm, st, header_bg=NAVY),
                                        st, "P/E on projected EPS uses today's share price; it is arithmetic on the "
                                            "projection, not a valuation call or a target price."))
            ex += 1
        t = ft.get("reliability") or {}
        if t.get("rows"):
            story.append(_table_exhibit(ex, "How reliable is the projection? (tested on the company's own past)",
                                        ("count and %", "test error in percent"),
                                        data_table(t["columns"], t["rows"], CONTENT_W, 4.4 * cm, st, header_bg=NAVY),
                                        st, "Test error = average gap between what the method would have projected "
                                            "in earlier years and what was actually reported. Below 8% = High, "
                                            "8-18% = Medium, above 18% = Low confidence."))
            ex += 1
        for nline in fc.get("notes", []):
            story.append(Paragraph(esc(nline), st["bullet"], bulletText="•"))
        story += [Paragraph(f"<b>Read with care:</b> {esc(fc.get('caveat', ''))}", st["small"]), Spacer(1, 6)]
    elif fc.get("error"):
        story += [Paragraph("Future outlook: model projections", st["h1"]),
                  Paragraph(esc(f"Projections were not produced: {fc['error']}."), st["body"])]

    # ---------------- financial summary tables
    tables = report.get("tables", {})
    story += [CondPageBreak(10 * cm), Paragraph("Financial Summary", st["h1"]),
              Paragraph("Source: company filings via Screener.in. The unit is printed above each table. "
                        + CRORE_HELP + ".", st["small"]),
              Spacer(1, 4)]
    for key, title in (("profit_loss", "Profit & Loss"), ("quarterly", "Quarterly Results"),
                       ("balance_sheet", "Balance Sheet"), ("cash_flow", "Cash Flows"),
                       ("key_ratios", "Key Ratios (calculated)")):
        t = tables.get(key) or {}
        if not t.get("rows"):
            continue
        story.append(_table_exhibit(ex, title, unit_of(key),
                                    data_table(t["columns"], t["rows"], CONTENT_W, 5.2 * cm, st), st))
        ex += 1

    # ---------------- financial health & warning signs (computed by code)
    h = report.get("health") or {}
    if h:
        story += [CondPageBreak(9 * cm), Paragraph("Financial Health &amp; Warning Signs", st["h1"]),
                  Paragraph("Calculated from the company's reported figures (Screener.in); no AI involved in these "
                            "numbers.", st["small"])]
        p = h.get("piotroski") or {}
        if p.get("available"):
            rows = [[{True: "<font color='#12783C'>✔ yes</font>", False: "<font color='#B91C1C'>✖ no</font>",
                      None: "– n/a"}[t["result"]], esc(t["test"]), esc(t["evidence"])] for t in p["tests"]]
            block = [Paragraph(f"<font color='#E8710A'><b>Exhibit {ex}:</b></font> <b>Piotroski F-score: "
                               f"{p['score']} of {p['out_of']} ({esc(p['band'])})</b> — {esc(p['year'])} compared with "
                               f"{esc(p['compared_with'])}", st["h3"]),
                     _link_table(["Result", "Test", "Evidence"], rows,
                                 [1.6 * cm, 7.0 * cm, CONTENT_W - 8.6 * cm], st),
                     Paragraph("Nine yes/no tests of profitability, funding and efficiency (Piotroski, 2000). 7 or more "
                               "= strong, 4–6 = average, 3 or less = weak. Tests the data cannot support are n/a and "
                               "not counted.", st["tiny"]), Spacer(1, 8)]
            story.append(KeepTogether(block))
            ex += 1
        rf = h.get("red_flags") or {}
        box = [Paragraph("Warning signs", st["h2"])]
        if rf.get("flags"):
            for fl in rf["flags"]:
                col = "#B91C1C" if fl.get("level") == "high" else "#B45309"
                box.append(Paragraph(f"<font color='{col}'><b>{esc(fl['flag'])}</b></font> — {esc(fl['evidence'])}",
                                     st["bullet"], bulletText="•"))
        elif rf.get("checked"):
            box.append(Paragraph(f"None of the {len(rf['checked'])} warning-sign checks fired.", st["body"]))
        if rf.get("checked"):
            box.append(Paragraph("Checked: " + esc("; ".join(rf["checked"])) + ".", st["tiny"]))
        story.append(KeepTogether(box))
        why = {"working_capital": ("Working capital (days)", "days",
                                   "Days to collect cash from customers, days stock is held and days taken to pay "
                                   "suppliers. Rising days mean more cash is stuck in the business."),
               "earnings_quality": ("Earnings quality", ("% and times (x)", ""),
                                    "Whether profit comes from the core business and turns into cash."),
               "cash_capex": ("Cash flow, capital spending and free cash flow", ("₹ crore and %", ""),
                              "Free cash flow = cash left after spending on plants and equipment."),
               "dupont": ("Return on equity breakdown (DuPont)", ("% and times (x)", ""),
                          "ROE = profit margin × asset turnover × equity multiplier (year-end figures). ROE driven by "
                          "borrowing is riskier than ROE driven by margins.")}
        for k, (title, unit, note) in why.items():
            t = h.get(k) or {}
            if not t.get("rows"):
                continue
            rows = [{"metric": r["metric"], "values": r["values"]} for r in t["rows"]]
            if k == "cash_capex" and t.get("fcf_source"):
                note += f" Source of free cash flow: {t['fcf_source']}."
            story.append(_table_exhibit(ex, title, unit if isinstance(unit, tuple) else (unit, ""),
                                        data_table(t["columns"], rows, CONTENT_W, 6.4 * cm, st), st, note))
            ex += 1
        risk = h.get("risk") or {}
        if risk.get("rows"):
            story.append(_table_exhibit(ex, "Share price risk", ("% and times", ""),
                                        _link_table(["Measure", "Value", "What it means"],
                                                    [[esc(a), f"<b>{esc(b)}</b>", esc(c)] for a, b, c in risk["rows"]],
                                                    [5.6 * cm, 2.4 * cm, CONTENT_W - 8.0 * cm], st), st,
                                        f"From daily closing prices up to {risk.get('as_of', '')}."))
            ex += 1
        act, docs = h.get("actions") or {}, h.get("documents") or {}
        t = act.get("dividends") or {}
        if t.get("rows"):
            story.append(_table_exhibit(ex, "Dividends", ("₹ per share and %", ""),
                                        data_table(t["columns"], [{"metric": r["metric"], "values": r["values"]}
                                                                  for r in t["rows"]], CONTENT_W, 6.4 * cm, st), st))
            ex += 1
        extra = []
        y = act.get("yahoo") or {}
        if y.get("splits"):
            extra.append("Splits / bonus (Yahoo Finance): " + ", ".join(f"{s_['date']} ratio {s_['ratio']:g}"
                                                                         for s_ in y["splits"]))
        for f_ in (act.get("filings") or [])[:5]:
            extra.append(f"{f_['date']} · {_a(f_.get('url', ''), f_['title'])}")
        for r in docs.get("credit_ratings") or []:
            extra.append(f"Credit rating ({esc(r.get('agency') or 'agency')}): {_a(r['url'], r['title'])} "
                         f"{esc(r.get('detail') or '')}")
        for r in docs.get("annual_reports") or []:
            extra.append("Annual report: " + _a(r["url"], r["title"]))
        for c in docs.get("concalls") or []:
            extra.append(f"Earnings call {esc(c.get('period'))}: " +
                         " · ".join(_a(v, k_) for k_, v in (c.get("links") or {}).items()))
        if extra:
            story.append(Paragraph("Corporate actions, credit rating and documents", st["h2"]))
            story += [Paragraph(x, st["link"], bulletText="•") for x in extra]
        if h.get("not_included"):
            story.append(Paragraph("Not included: " + esc(" ".join(h["not_included"])), st["tiny"]))

    # ---------------- peers
    peers = report.get("peers") or {}
    if peers.get("rows"):
        cols = peers["columns"][2:]
        rows = [{"metric": p["name"], "values": [p["values"].get(c, "") for c in cols]} for p in peers["rows"]]
        if peers.get("median"):
            rows.append({"metric": "Median", "values": [peers["median"].get(c, "") for c in cols], "bold": True})
        story.append(_table_exhibit(ex, "Peer comparison (companies in the same industry, from Screener)",
                                    unit_of("peers"),
                                    data_table(cols, rows, CONTENT_W, 3.6 * cm, st, font_size=6.4), st))
        ex += 1
    else:
        story += [Paragraph("Peer comparison", st["h2"]),
                  Paragraph("Screener did not return a peer list for this company in this capture.", st["small"])]

    # ---------------- supplementary data from other websites
    sup = report.get("supplementary") or {}
    if sup.get("items") or sup.get("estimates") or sup.get("links"):
        story += [CondPageBreak(11 * cm), Paragraph("Additional data from other websites", st["h1"]),
                  Paragraph("Screener.in is the main source of this report. The figures below are ones Screener "
                            "does not publish, or extra points that matter for the analysis. They are not part of "
                            "the scorecard, and each one is shown with the website it came from. Open the link to "
                            "check a value before relying on it.", st["body"])]
        w = [5.0 * cm, 3.0 * cm, 2.3 * cm, 3.3 * cm, CONTENT_W - 13.6 * cm]
        if sup.get("items"):
            rows = []
            for it in sup["items"]:
                how = {"yfinance": "read by yfinance library", "NSE API": "read from NSE's official quote data",
                   "Value Research page": "read from its stock page"}.get(
                    it.get("via")) or ("found by AI search" + ("" if it.get("seen_in_search") else ", page not confirmed"))
                note = "; ".join(x for x in [it.get("why"), how] if x)
                if it.get("flag"):
                    note += f" ⚠ {it['flag']}"
                rows.append([esc(it["metric"]), f"<b>{esc(it['value'])}</b>", esc(it.get("period") or "–"),
                             _a(it.get("url", ""), it["source"]), esc(note)])
            story.append(_table_exhibit(ex, "Figures not available on Screener", unit_of("supplementary"),
                                        _link_table(["Data point", "Value", "Period", "Source (click to open)",
                                                     "Why it matters / how obtained"], rows, w, st), st))
            ex += 1
        if sup.get("estimates"):
            rows = [[esc(it["metric"]), f"<b>{esc(it['value'])}</b>", esc(it.get("period") or "–"),
                     _a(it.get("url", ""), it["source"]),
                     esc(f"{it['analysts']} analysts" if it.get("analysts") else "analyst consensus")]
                    for it in sup["estimates"]]
            story.append(_table_exhibit(ex, "Analysts' estimates (third-party views, not ours)",
                                        ("₹ per share", "revenue estimates in ₹ crore"),
                                        _link_table(["Estimate", "Value", "Period", "Source (click to open)", "Basis"],
                                                    rows, w, st), st))
            ex += 1
        if sup.get("links"):
            story.append(Paragraph("Connected websites", st["h3"]))
            for ln in sup["links"]:
                story.append(Paragraph(f"{_a(ln['url'], ln['site'])} <font color='#6B7280'>— {esc(ln.get('note', ''))}"
                                       f"</font>", st["link"], bulletText="•"))
        for nline in sup.get("notes", []):
            story.append(Paragraph(esc(nline), st["tiny"]))
        story.append(Spacer(1, 6))

    # ---------------- scorecard detail
    sc_rows = [{"metric": f"{it['name']} (weight {it['weight']}%)",
                "values": [f"{it['score']:.1f}/10", "; ".join(it["rationale"])]} for it in report.get("scorecard", [])]
    if sc_rows:
        t = Table([[Paragraph("<b>Factor</b>", st["cell_hdr_l"]), Paragraph("<b>Score</b>", st["cell_hdr"]),
                    Paragraph("<b>Evidence from data</b>", st["cell_hdr_l"])]] +
                  [[Paragraph(esc(r["metric"]), st["cell"]), Paragraph(esc(r["values"][0]), st["cell_r"]),
                    Paragraph(esc(r["values"][1]), st["cell"])] for r in sc_rows],
                  colWidths=[4.6 * cm, 1.6 * cm, CONTENT_W - 6.2 * cm], repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY), ("LINEBELOW", (0, 1), (-1, -1), 0.25, LINE),
                               ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(KeepTogether([Paragraph("Scorecard detail", st["h2"]), t, Spacer(1, 6)]))

    # ---------------- strengths / risks / monitorables
    for key, title in (("key_strengths", "Key strengths"), ("key_risks", "Key risks"),
                       ("monitorables", "Key monitorables")):
        items = report.get(key) or []
        if items:
            story.append(Paragraph(title, st["h2"]))
            for b in items:
                story.append(Paragraph(esc(b), st["bullet"], bulletText="•"))

    # ---------------- news & announcements
    groups = report.get("news_by_source") or []
    if not groups and report.get("news"):  # reports made before news_by_source existed
        tmp: dict = {}
        for n in report["news"]:
            tmp.setdefault(n.get("source") or "Other", []).append(n)
        groups = [{"source": k, "items": v[:6]} for k, v in tmp.items()]
    anns = report.get("announcements") or []
    insights = report.get("news_takeaways") or []
    if groups or anns or insights:
        story += [CondPageBreak(7 * cm), Paragraph("News and announcements", st["h1"])]
        srcs = report.get("news_sources") or [g["source"] for g in groups]
        story.append(Paragraph("Latest news from " + esc(", ".join(srcs)) + ". Each line shows the website, then "
                               "the headline (click to open the article) and the date.", st["small"]))
        from analysis.report import counts_line

        if counts_line(report):
            story.append(Paragraph(esc(counts_line(report)), st["tiny"]))
        # The report shows the main headlines per website (.env REPORT_NEWS_PER_SOURCE, PDF_NEWS_MAX);
        # the full list stays in the app: Analysis Report -> "All headlines found".
        from core.config import get_settings

        cfg = get_settings()
        per, cap = cfg.report_news_per_source or 5, cfg.pdf_news_max or 70
        printed = 0
        total = sum((report.get("news_counts") or {}).values()) or sum(len(g["items"]) for g in groups)
        for g in groups:
            for n in g["items"][:per]:
                if printed >= cap:
                    break
                d = str(n.get("published_at") or "")[:10]
                story.append(Paragraph(f"<b>{esc(g['source'])}</b> — <link href='{esc(n.get('url', ''))}'>"
                                       f"{esc(n.get('title', ''))}</link>"
                                       + (f" <font color='#6B7280'>({esc(d)})</font>" if d else ""),
                                       st["link"], bulletText="•"))
                printed += 1
        if total > printed:
            story.append(Paragraph(f"Showing the {printed} main headlines of {total} found (up to {per} per website: "
                                   "results, orders, deals, dividends and management news first). "
                                   "The full list is in the app: Analysis Report → All headlines found.",
                                   st["tiny"]))
        if not groups:
            story.append(Paragraph("No recent headlines were found on these websites.", st["small"]))
        if insights:
            box = [Paragraph("Key insights from the news", st["h2"])]
            box += [Paragraph(esc(b), st["bullet"], bulletText="•") for b in insights]
            story.append(KeepTogether(box))
        if anns:
            story.append(Paragraph("Exchange announcements (company filings, via Screener)", st["h2"]))
            for a in anns[:10]:
                d = str(a.get("date") or "")[:10]
                txt = f"<b>{esc(d)}</b> · <link href='{esc(a.get('url', ''))}'>{esc(a.get('title', ''))}</link>"
                if a.get("summary"):
                    txt += f" — {esc(a['summary'])}"
                story.append(Paragraph(txt, st["link"], bulletText="•"))

    # ---------------- quality checks (guardrails)
    # The detailed check log is for reviewers (app + database); readers only get the note and data notes above.
    q = report.get("quality_checks") if get_settings().quality_details_in_pdf else None
    if q:
        s = q.get("summary", {})
        story += [CondPageBreak(6 * cm), Paragraph("Quality checks", st["h1"]),
                  Paragraph(esc(f"Before this report was produced, {s.get('total', 0)} automatic checks ran: "
                                f"{s.get('pass', 0)} passed, {s.get('fixed', 0)} fixed automatically, "
                                f"{s.get('warn', 0)} warnings, {s.get('fail', 0)} failed. "
                                f"{G.OUTCOME_TEXT.get(report.get('narrative_check', ''), '')}. Every number in the "
                                "report text was compared with the source data; values from other websites were "
                                "range-checked and cross-checked with Screener."), st["body"])]
        mark = {"pass": "<font color='#12783C'>✔ pass</font>", "fixed": "<font color='#1C4DA0'>fixed</font>",
                "warn": "<font color='#B45309'>⚠ warn</font>", "fail": "<font color='#B91C1C'>✖ fail</font>"}
        rows = [[mark.get(c["status"], esc(c["status"])), esc(c["group"]), esc(c["check"]), esc(c["detail"])]
                for c in q.get("checks", [])]
        story.append(_link_table(["Result", "Area", "Check", "Detail"], rows,
                                 [1.6 * cm, 3.0 * cm, 5.6 * cm, CONTENT_W - 10.2 * cm], st))
        removed = q.get("removed_text") or []
        rem_sup = (report.get("supplementary") or {}).get("removed_by_checks") or []
        if removed or rem_sup:
            story.append(Paragraph("Removed by the checks", st["h3"]))
            for r in removed[:25]:
                story.append(Paragraph(f"<b>{esc(r['where'])}</b>: “{esc(r['text'])}” — "
                                       f"<i>{esc(r['reason'])}</i>", st["small"], bulletText="•"))
            for r in rem_sup[:15]:
                story.append(Paragraph(f"<b>{esc(r['metric'])} = {esc(r['value'])}</b> ({esc(r['source'])}) — "
                                       f"<i>{esc(r['reason'])}</i>", st["small"], bulletText="•"))

    # ---------------- disclaimer
    story += [Spacer(1, 10), Paragraph("Disclaimer", st["h2"]),
              Paragraph(esc(report.get("disclaimer", "")), st["small"]),
              Paragraph(f"Report generated: {esc(report.get('generated_at', ''))} · Data captured: "
                        f"{esc(report.get('data_as_of', ''))} · Narrative model: {esc(report.get('model', ''))}",
                        st["tiny"])]

    doc.build([s for s in story if s is not None])
    return buf.getvalue()
