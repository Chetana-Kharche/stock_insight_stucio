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


def _exhibit(n: int, title: str, chart: dict | None, width: float, st: dict, source: str = "Screener.in"):
    """chart = {'png': bytes, 'unit': str} from exports.charts."""
    if not chart:
        return None
    img = _img(chart.get("png"), width)
    if img is None:
        return None
    return KeepTogether([x for x in [
        Paragraph(f"<font color='#E8710A'><b>Exhibit {n}:</b></font> <b>{esc(title)}</b>", st["h3"]),
        _unit(chart.get("unit", ""), st),
        img,
        Paragraph(f"Source: {esc(source)}, {APP_NAME}", st["tiny"]),
        Spacer(1, 6),
    ] if x is not None])


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
    summary_box = Table([[Paragraph(esc(report.get("executive_summary", "")), st["body"])]], colWidths=[main_w])
    summary_box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), LIGHT), ("LEFTPADDING", (0, 0), (-1, -1), 8),
                                     ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 6),
                                     ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                                     ("LINEBEFORE", (0, 0), (0, -1), 2.5, ORANGE)]))
    story += [summary_box, Spacer(1, 6)]
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
    if payload:
        exhibits = [
            ("Share price with 50/200-day moving averages", charts.price_chart(payload.get("price_history") or [])),
            ("Annual revenue and net profit", charts.annual_revenue_profit(payload)),
            ("Quarterly trend", charts.quarterly_trend(payload)),
            ("Margins and return ratios", charts.margins_returns(payload)),
            ("Valuation: trailing P/E vs 5-year median", charts.pe_chart(payload.get("pe_history") or {})),
            ("Shareholding pattern", charts.shareholding_trend(payload)),
        ]
    exhibits = [(t, c) for t, c in exhibits if c]
    if exhibits:
        head = [Paragraph("Exhibits", st["h1"]),
                Paragraph("The green line above each chart gives the unit of the numbers. " + CRORE_HELP + ".",
                          st["small"]), Spacer(1, 3)]
        for i, (title, chart) in enumerate(exhibits):
            block = _exhibit(ex, title, chart, chart_w, st)
            # keep the section heading on the same page as the first chart
            story.append(KeepTogether(head + [block]) if i == 0 else block)
            ex += 1

    # ---------------- model projections
    fc = report.get("forecast") or {}
    if fc.get("ok"):
        ft = fc.get("tables") or {}
        story += [CondPageBreak(9 * cm), Paragraph("Future outlook: model projections", st["h1"]),
                  Paragraph(esc(f"{fc.get('method', '')} Overall confidence: {fc.get('confidence', '–')}. "
                                f"Python libraries: {fc.get('libraries', '')}."), st["body"])]
        story.append(_exhibit(ex, "Reported history and projection for the next three fiscal years "
                                  "(dashed line = projection, shaded band = 80% range)",
                              charts.forecast_chart(fc), CONTENT_W, st,
                              source="Screener.in history; projection by statistical models"))
        ex += 1
        for key, title, unit_key, first in (("annual", "Projection by fiscal year (E = estimate by the model)",
                                             "forecast_annual", 5.4 * cm),
                                            ("quarterly", "Projection for the next four quarters",
                                             "forecast_quarterly", 5.4 * cm)):
            t = ft.get(key) or {}
            if t.get("rows"):
                story.append(_table_exhibit(ex, title, unit_of(unit_key),
                                            data_table(t["columns"], t["rows"], CONTENT_W, first, st, header_bg=NAVY),
                                            st, "Base case = weighted average of the models. Low and high case = "
                                                "80% range from each model's past test errors."))
                ex += 1
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
        t = ft.get("models") or {}
        if t.get("rows"):
            story.append(_table_exhibit(ex, "The individual models behind the base case", unit_of("forecast_annual"),
                                        data_table(t["columns"], t["rows"], CONTENT_W, 7.6 * cm, st, header_bg=NAVY),
                                        st, "Weight = share of each model in the base case; more accurate models "
                                            "in the past get a higher weight."))
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

    # ---------------- peers
    peers = report.get("peers") or {}
    if peers.get("rows"):
        cols = peers["columns"][2:]
        rows = [{"metric": p["name"], "values": [p["values"].get(c, "") for c in cols]} for p in peers["rows"]]
        if peers.get("median"):
            rows.append({"metric": "Median", "values": [peers["median"].get(c, "") for c in cols], "bold": True})
        story.append(_table_exhibit(ex, "Peer comparison", unit_of("peers"),
                                    data_table(cols, rows, CONTENT_W, 3.6 * cm, st, font_size=6.4), st))
        ex += 1

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
                how = "read by yfinance library" if it.get("via") == "yfinance" else (
                    "found by AI search" + ("" if it.get("seen_in_search") else ", page not confirmed"))
                rows.append([esc(it["metric"]), f"<b>{esc(it['value'])}</b>", esc(it.get("period") or "–"),
                             _a(it.get("url", ""), it["source"]),
                             esc("; ".join(x for x in [it.get("why"), how] if x))])
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
                       ("monitorables", "Key monitorables"), ("news_takeaways", "News takeaways")):
        items = report.get(key) or []
        if items:
            story.append(Paragraph(title, st["h2"]))
            for b in items:
                story.append(Paragraph(esc(b), st["bullet"], bulletText="•"))

    # ---------------- news & announcements
    anns = report.get("announcements") or []
    news = report.get("news") or []
    if anns or news:
        story += [CondPageBreak(6 * cm), Paragraph("Recent announcements and news", st["h1"])]
        for a in anns[:10]:
            d = str(a.get("date") or "")[:10]
            txt = f"<b>{esc(d)}</b> · <link href='{esc(a.get('url', ''))}'>{esc(a.get('title', ''))}</link>"
            if a.get("summary"):
                txt += f" — {esc(a['summary'])}"
            story.append(Paragraph(txt, st["link"], bulletText="•"))
        if news:
            story.append(Spacer(1, 4))
            for n in news[:12]:
                d = str(n.get("published_at") or "")[:10]
                txt = (f"<b>{esc(d)}</b> · <link href='{esc(n.get('url', ''))}'>{esc(n.get('title', ''))}</link>"
                       f" <font color='#6B7280'>({esc(n.get('source') or '')})</font>")
                story.append(Paragraph(txt, st["link"], bulletText="•"))

    # ---------------- disclaimer
    story += [Spacer(1, 10), Paragraph("Disclaimer", st["h2"]),
              Paragraph(esc(report.get("disclaimer", "")), st["small"]),
              Paragraph(f"Report generated: {esc(report.get('generated_at', ''))} · Data captured: "
                        f"{esc(report.get('data_as_of', ''))} · Narrative model: {esc(report.get('model', ''))}",
                        st["tiny"])]

    doc.build([s for s in story if s is not None])
    return buf.getvalue()
