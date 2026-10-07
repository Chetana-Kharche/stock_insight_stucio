"""PDF export of the scraped Screener data, laid out like the Screener company page."""
from __future__ import annotations

import io
import json
from datetime import datetime

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (CondPageBreak, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from core.config import APP_NAME
from core.units import unit_of
from scraper.parser import FIN_SECTIONS
from exports.pdf_common import (LIGHT, LINE, MUTED, NAVY, ORANGE, data_table, esc, register_fonts, styles)

PAGE = landscape(A4)
M = 1.1 * cm
W = PAGE[0] - 2 * M
UNIT_LABEL = {"INR_CRORE": "₹ crore", "PERCENT": "percent (%)", "INR": "₹ (rupees)", "DAYS": "days", "COUNT": "count",
              "RATIO": "ratio"}


def _footer(meta: dict):
    def draw(canvas, doc):
        canvas.saveState()
        canvas.setFont("DV", 6.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(M, 0.6 * cm, f"{meta.get('name', '')} · {meta.get('basis', '')} · source: "
                                       f"{meta.get('source_url', '')} · captured {meta.get('captured_at', '')[:19]}")
        canvas.drawRightString(PAGE[0] - M, 0.6 * cm, f"{APP_NAME} · page {doc.page}")
        canvas.restoreState()
    return draw


def _unit(key: str, st: dict) -> Paragraph:
    """Green 'Unit: ₹ crore' line printed above a table."""
    unit, detail = unit_of(key)
    html = f"<font color='#15803D'><b>Unit: {esc(unit)}</b></font>"
    if detail:
        html += f" <font color='#6B7280'>· {esc(detail)}</font>"
    return Paragraph(html, ParagraphStyle("unit", parent=st["base"], fontSize=7.4, leading=10, spaceAfter=2))


def _section_rows(sec: dict, with_breakdowns: bool) -> list[dict]:
    rows = []
    for r in sec["rows"]:
        rows.append({"metric": r["metric"] + (" +" if r.get("schedules") else ""), "values": r["values"],
                     "bold": r.get("is_bold")})
        if with_breakdowns:
            for sub, vals in (r.get("schedules") or {}).items():
                rows.append({"metric": sub, "values": vals["values"], "indent": True})
    return rows


def build_screener_pdf(payload: dict, with_breakdowns: bool = True) -> bytes:
    register_fonts()
    st = styles()
    meta = payload.get("meta", {})
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=PAGE, leftMargin=M, rightMargin=M, topMargin=M, bottomMargin=1.1 * cm,
                            title=f"{meta.get('name', '')} - Screener data", author=APP_NAME)
    story: list = []

    # ---------- header card
    captured = meta.get("captured_at", "")
    try:
        captured = datetime.fromisoformat(captured).strftime("%d %b %Y, %H:%M UTC")
    except (TypeError, ValueError):
        pass
    left = [Paragraph(esc(meta.get("name", "")), st["title"]),
            Paragraph(esc(f"NSE:{meta.get('nse_symbol') or '–'} · BSE:{meta.get('bse_code') or '–'} · {meta.get('basis')}"),
                      st["subtitle"]),
            Paragraph(esc(" › ".join(x for x in [meta.get("broad_sector"), meta.get("sector"),
                                                 meta.get("broad_industry"), meta.get("industry")] if x)),
                      st["small"])]
    right_rows = [["Captured", captured], ["Latest period", meta.get("latest_period") or "–"],
                  ["Upcoming results", meta.get("upcoming_result_date") or "–"],
                  ["Parser", meta.get("parser_version") or "–"]]
    right = Table([[Paragraph(esc(k), st["cell"]), Paragraph(esc(v), st["cell_r"])] for k, v in right_rows],
                  colWidths=[3 * cm, 5 * cm])
    card = Table([[left, right]], colWidths=[W - 8.4 * cm, 8.4 * cm])
    card.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                              ("BACKGROUND", (0, 0), (-1, -1), LIGHT), ("LEFTPADDING", (0, 0), (-1, -1), 8),
                              ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story += [card, Spacer(1, 8)]

    # ---------- summary ratios grid (3 per row)
    ratios = payload.get("summary_ratios", [])
    if ratios:
        story.append(Paragraph("Summary ratios", st["h1"]))
        cells = []
        for r in ratios:
            cells.append([Paragraph(esc(r["name"].upper()), st["small"]),
                          Paragraph(f"<b>{esc(r['value_text'])}</b>",
                                    ParagraphStyle("v", parent=st["base"], fontSize=11, leading=14)),
                          Paragraph(esc(UNIT_LABEL.get(r["unit"], r["unit"])), st["tiny"])])
        grid, row = [], []
        for c in cells:
            row.append(c)
            if len(row) == 3:
                grid.append(row)
                row = []
        if row:
            grid.append(row + [""] * (3 - len(row)))
        t = Table(grid, colWidths=[W / 3] * 3)
        t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.4, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 5),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        story += [t, Spacer(1, 6)]

    if payload.get("about"):
        story += [Paragraph("About", st["h2"]), Paragraph(esc(payload["about"]), st["body"])]
    if payload.get("pros") or payload.get("cons"):
        pros = [Paragraph("<b>Pros</b>", ParagraphStyle("p", parent=st["base"], textColor="#15803D"))] + \
               [Paragraph("• " + esc(x), st["base"]) for x in payload.get("pros", [])]
        cons = [Paragraph("<b>Cons</b>", ParagraphStyle("c", parent=st["base"], textColor="#B91C1C"))] + \
               [Paragraph("• " + esc(x), st["base"]) for x in payload.get("cons", [])]
        t = Table([[pros, cons]], colWidths=[W / 2, W / 2])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story += [Spacer(1, 4), t, Paragraph("Pros/cons are machine generated by Screener.", st["tiny"])]

    # ---------- peers
    peers = payload.get("peers") or {}
    if peers.get("rows"):
        cols = peers["columns"][2:]
        rows = [{"metric": f"{int(p['rank']) if p.get('rank') else ''}. {p['name']}",
                 "values": [p["values"].get(c, "") for c in cols]} for p in peers["rows"]]
        if peers.get("median"):
            rows.append({"metric": peers["median"]["name"], "values": [peers["median"]["values"].get(c, "")
                                                                        for c in cols], "bold": True})
        story += [CondPageBreak(5 * cm), Paragraph("Peer comparison", st["h1"]),
                  Paragraph(esc(" › ".join(x for x in [meta.get("broad_industry"), meta.get("industry")] if x)),
                            st["small"]),
                  _unit("peers", st),
                  data_table(cols, rows, W, 5 * cm, st, header_bg=NAVY), Spacer(1, 8)]

    # ---------- financial sections
    for sid in FIN_SECTIONS:  # fixed order (jsonb does not keep key order)
        sec = payload.get("sections", {}).get(sid)
        if not sec:
            continue
        cols = [c["label"] for c in sec["columns"]]
        fs = 6.6 if len(cols) <= 13 else 5.8
        story += [CondPageBreak(6 * cm),
                  Paragraph(esc(sec.get("title", sid)), st["h1"]),
                  Paragraph(esc(sec.get("note", "")), st["small"]),
                  _unit(sid, st),
                  data_table(cols, _section_rows(sec, with_breakdowns), W, 4.6 * cm, st, font_size=fs,
                             header_bg=NAVY),
                  Spacer(1, 6)]
        if sid == "profit-loss" and payload.get("growth"):
            blocks = []
            for g in payload["growth"]:
                rows = [[Paragraph(esc(it["period"]), st["cell"]), Paragraph(esc(it["value_text"]), st["cell_r"])]
                        for it in g["rows"]]
                t = Table([[Paragraph(f"<b>{esc(g['title'].upper())}</b>", st["cell_b"]), ""]] + rows,
                          colWidths=[W / 4 * 0.6 - 6, W / 4 * 0.4 - 6])
                t.setStyle(TableStyle([("SPAN", (0, 0), (-1, 0)), ("LINEBELOW", (0, 0), (-1, -1), 0.25, LINE),
                                       ("LINEBELOW", (0, 0), (-1, 0), 1, ORANGE)]))
                blocks.append(t)
            blocks += [""] * (4 - len(blocks) % 4 if len(blocks) % 4 else 0)
            grid = [blocks[i:i + 4] for i in range(0, len(blocks), 4)]
            gt = Table(grid, colWidths=[W / 4] * 4)
            gt.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
            story += [KeepTogether([gt]), Spacer(1, 6)]

    # ---------- shareholding
    shp = payload.get("shareholding") or {}
    for key, title in (("quarterly", "Shareholding Pattern — quarterly"), ("yearly", "Shareholding Pattern — yearly")):
        sec = shp.get(key)
        if not sec:
            continue
        cols = [c["label"] for c in sec["columns"]]
        story += [CondPageBreak(5 * cm), Paragraph(title, st["h1"]), _unit("shareholding", st),
                  data_table(cols, _section_rows(sec, False), W, 4.6 * cm, st, font_size=6.6, header_bg=NAVY),
                  Spacer(1, 4)]
    if shp.get("note"):
        story.append(Paragraph(esc(shp["note"]), st["tiny"]))

    # ---------- documents
    docs = payload.get("documents") or {}
    if any(docs.values()):
        story += [CondPageBreak(5 * cm), Paragraph("Documents", st["h1"])]
        if docs.get("announcements"):
            story.append(Paragraph("Announcements", st["h2"]))
            for a in docs["announcements"]:
                txt = (f"<b>{esc(str(a.get('date') or '')[:10])}</b> · "
                       f"<link href='{esc(a['url'])}'>{esc(a['title'])}</link>")
                if a.get("summary"):
                    txt += f" — {esc(a['summary'])}"
                story.append(Paragraph(txt, st["link"], bulletText="•"))
        if docs.get("annual_reports"):
            story.append(Paragraph("Annual reports", st["h2"]))
            for a in docs["annual_reports"]:
                story.append(Paragraph(f"<link href='{esc(a['url'])}'>{esc(a['title'])}</link> "
                                       f"<font color='#6B7280'>{esc(a.get('source', ''))}</font>",
                                       st["link"], bulletText="•"))
        if docs.get("credit_ratings"):
            story.append(Paragraph("Credit ratings", st["h2"]))
            for a in docs["credit_ratings"]:
                story.append(Paragraph(f"<link href='{esc(a['url'])}'>{esc(a['title'])}</link> "
                                       f"<font color='#6B7280'>{esc(a.get('meta', ''))}</font>",
                                       st["link"], bulletText="•"))
        if docs.get("concalls"):
            story.append(Paragraph("Concalls", st["h2"]))
            for cc in docs["concalls"]:
                links = " · ".join(f"<link href='{esc(u)}'>{esc(k)}</link>" for k, u in cc["links"].items())
                story.append(Paragraph(f"<b>{esc(cc['period'])}</b> — {links}", st["link"], bulletText="•"))

    story += [Spacer(1, 8), Paragraph(
        "Data scraped from the public Screener.in company page for personal/educational use. "
        "Verify with company filings before relying on it.", st["tiny"])]
    doc.build(story, onFirstPage=_footer(meta), onLaterPages=_footer(meta))
    return buf.getvalue()


def payload_to_json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, indent=2, ensure_ascii=False, default=str).encode("utf-8")
