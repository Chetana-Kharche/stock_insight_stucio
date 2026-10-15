"""Pure HTML builders (no Streamlit import) for the Screener-style view."""
from __future__ import annotations

from datetime import datetime
from html import escape

from core.units import unit_of

UNIT_LABEL = {"INR_CRORE": "₹ crore", "PERCENT": "percent (%)", "INR": "₹ (rupees)", "DAYS": "days", "COUNT": "count",
              "RATIO": "ratio (x)"}


def e(x) -> str:
    return escape(str(x if x is not None else ""))


def header_card(payload: dict, run: dict | None = None) -> str:
    m = payload.get("meta", {})
    captured = m.get("captured_at", "")
    try:
        captured = datetime.fromisoformat(captured).strftime("%b %d, %Y · %I:%M %p UTC")
    except (TypeError, ValueError):
        pass
    trigger = "manual fetch" if run is None else f"run #{run.get('id', m.get('run_id', ''))}"
    classification = " › ".join(x for x in [m.get("broad_sector"), m.get("broad_industry"), m.get("industry")] if x)
    return f"""
<div class="sis-card"><div class="sis-head">
  <div>
    <div><span class="name">{e(m.get('name'))}</span><span class="sis-tag">VERIFIED CAPTURE</span></div>
    <div class="sis-mono">NSE:{e(m.get('nse_symbol') or '–')} · BSE:{e(m.get('bse_code') or '–')} · {e(m.get('basis'))}</div>
    <div class="sis-sub" style="margin-top:6px">{e(classification)}</div>
    {f'<div class="sis-sub"><a href="{e(m.get("website"))}" target="_blank">Company website ↗</a> · <a href="{e(m.get("source_url"))}" target="_blank">Open source page ↗</a></div>' if m.get('website') else f'<div class="sis-sub"><a href="{e(m.get("source_url"))}" target="_blank">Open source page ↗</a></div>'}
  </div>
  <div class="sis-kv">
    <span class="k">Captured</span><span class="v">{e(captured)}</span>
    <span class="k">Latest period</span><span class="v">{e(m.get('latest_period') or '–')}</span>
    <span class="k">Upcoming results</span><span class="v">{e(m.get('upcoming_result_date') or '–')}</span>
    <span class="k">Trigger</span><span class="v">{e(trigger)}</span>
    <span class="k">Parser</span><span class="v">{e(m.get('parser_version'))}</span>
    <span class="k">Facts stored</span><span class="v">{e(m.get('facts_stored', '–'))}</span>
  </div>
</div></div>"""


def ratio_grid(payload: dict) -> str:
    cells = []
    for r in payload.get("summary_ratios", []):
        cells.append(f"""<div class="sis-ratio"><div class="n">{e(r['name'])}</div>
            <div class="v">{e(r['value_text'])}</div><div class="u">{e(UNIT_LABEL.get(r['unit'], r['unit']))}</div></div>""")
    return f"""<div class="sis-card"><div class="sis-grid">{''.join(cells)}</div></div>"""


def data_table(columns: list[str], rows: list[dict], show_breakdowns: bool = True) -> str:
    head = "<tr><th>Metric</th>" + "".join(f"<th>{e(c)}</th>" for c in columns) + "</tr>"
    body = []
    for r in rows:
        plus = ' <span class="plus">+</span>' if (r.get("schedules") or r.get("schedule_parent") or
                                                   r.get("shareholder_class")) else ""
        cls = "bold" if r.get("is_bold") else ""
        vals = "".join(f"<td>{e(v) if v not in ('', None) else '–'}</td>" for v in r["values"])
        body.append(f'<tr class="{cls}"><td>{e(r["metric"])}{plus}</td>{vals}</tr>')
        if show_breakdowns:
            for sub, sv in (r.get("schedules") or {}).items():
                svals = "".join(f"<td>{e(v) if v not in ('', None) else '–'}</td>" for v in sv["values"])
                body.append(f'<tr class="sub"><td>{e(sub)}</td>{svals}</tr>')
    return f'<div class="sis-tablewrap"><table class="sis-table"><thead>{head}</thead><tbody>{"".join(body)}</tbody></table></div>'


def unit_html(key: str) -> str:
    unit, detail = unit_of(key)
    return f'<div class="sis-unit"><b>Unit: {e(unit)}</b>{e(detail)}</div>' if unit else ""


def section_card(sec: dict, key: str, basis: str, show_breakdowns: bool) -> str:
    cols = [c["label"] for c in sec["columns"]]
    sub = " · ".join(x for x in [basis, sec.get("note", "")] if x)
    return f"""<div class="sis-card"><div class="sis-head"><div><h3>{e(sec.get('title', key))}</h3>
        <div class="sis-sub" style="margin-bottom:6px">{e(sub)}</div>{unit_html(key)}</div>
        <div class="sis-mono">{e(key)}</div></div>{data_table(cols, sec['rows'], show_breakdowns)}</div>"""


def growth_tables(growth: list[dict]) -> str:
    """Screener's four compounded-growth boxes, shown two per row."""
    blocks = []
    for g in growth:
        rows = "".join(f"<tr><td>{e(it['period'])}</td><td>{e(it['value_text'])}</td></tr>" for it in g["rows"])
        blocks.append(f"""<div class="vr-growth"><div class="h">{e(g['title'])}</div>
            <table class="sis-table compact"><thead><tr><th>Period</th><th>Value</th></tr></thead>
            <tbody>{rows}</tbody></table></div>""")
    return f'<div class="vr-growth-grid">{"".join(blocks)}</div>'


def peers_card(peers: dict, meta: dict) -> str:
    if not peers or not peers.get("rows"):
        return ""
    cols = peers["columns"][2:]
    head = "<tr><th>Company</th>" + "".join(f"<th>{e(c)}</th>" for c in cols) + "</tr>"
    body = []
    for p in peers["rows"]:
        link = f'https://www.screener.in{p["url"]}' if p.get("url") else "#"
        body.append(f'<tr><td>{int(p["rank"]) if p.get("rank") else ""}. <a href="{e(link)}" target="_blank">{e(p["name"])}</a></td>'
                    + "".join(f"<td>{e(p['values'].get(c, ''))}</td>" for c in cols) + "</tr>")
    if peers.get("median"):
        md = peers["median"]
        body.append(f'<tr class="bold"><td>{e(md["name"])}</td>' +
                    "".join(f"<td>{e(md['values'].get(c, ''))}</td>" for c in cols) + "</tr>")
    industry = " › ".join(x for x in [meta.get("broad_industry"), meta.get("industry")] if x)
    return f"""<div class="sis-card"><div class="sis-head"><div><h3>Industry peers</h3>
        <div class="sis-sub" style="margin-bottom:6px">{e(industry)}</div>{unit_html('peers')}</div>
        <div class="sis-mono">peers</div></div>
        <div class="sis-tablewrap"><table class="sis-table"><thead>{head}</thead><tbody>{''.join(body)}</tbody></table></div></div>"""


def documents_card(docs: dict) -> str:
    if not docs or not any(docs.values()):
        return ""
    parts = []
    if docs.get("announcements"):
        items = "".join(
            f'<li><a href="{e(a["url"])}" target="_blank">{e(a["title"])} ↗</a><br>'
            f'<span class="d">{e(str(a.get("date") or "")[:10])} {("— " + e(a["summary"])) if a.get("summary") else ""}</span></li>'
            for a in docs["announcements"])
        parts.append(f"<h4>Announcements</h4><ul>{items}</ul>")
    if docs.get("annual_reports"):
        items = "".join(f'<li><a href="{e(a["url"])}" target="_blank">{e(a["title"])} ↗</a> '
                        f'<span class="d">{e(a.get("source", ""))}</span></li>' for a in docs["annual_reports"])
        parts.append(f"<h4>Annual reports</h4><ul>{items}</ul>")
    if docs.get("credit_ratings"):
        items = "".join(f'<li><a href="{e(a["url"])}" target="_blank">{e(a["title"])} ↗</a> '
                        f'<span class="d">{e(a.get("meta", ""))}</span></li>' for a in docs["credit_ratings"])
        parts.append(f"<h4>Credit ratings</h4><ul>{items}</ul>")
    if docs.get("concalls"):
        items = "".join(f'<li><b>{e(c["period"])}</b> — ' + " · ".join(
            f'<a href="{e(u)}" target="_blank">{e(k)}</a>' for k, u in c["links"].items()) + "</li>"
                        for c in docs["concalls"])
        parts.append(f"<h4>Concalls</h4><ul>{items}</ul>")
    return f'<div class="sis-card sis-doc">{"".join(parts)}</div>'


def kv_rows_table(rows: list[list[str]]) -> str:
    body = "".join(f"<tr><td>{e(k)}</td><td>{e(v)}</td></tr>" for k, v in rows)
    return f'<div class="sis-tablewrap"><table class="sis-table"><tbody>{body}</tbody></table></div>'


def simple_table(columns: list[str], rows: list[dict]) -> str:
    head = "<tr><th></th>" + "".join(f"<th>{e(c)}</th>" for c in columns) + "</tr>"
    body = "".join(
        f'<tr class="{"bold" if r.get("bold") else ""}"><td>{e(r["metric"])}</td>' +
        "".join(f"<td>{e(v) if v not in ('', None) else '–'}</td>" for v in r["values"]) + "</tr>" for r in rows)
    return f'<div class="sis-tablewrap"><table class="sis-table"><thead>{head}</thead><tbody>{body}</tbody></table></div>'


def indent_table(columns: list[str], rows: list[dict]) -> str:
    """Like simple_table but rows flagged 'indent' are shown as lighter sub-rows (projection low/high cases)."""
    head = "<tr><th></th>" + "".join(f"<th>{e(c)}</th>" for c in columns) + "</tr>"
    body = []
    for r in rows:
        cls = "bold" if r.get("bold") else ("sub" if r.get("indent") else "")
        vals = list(r["values"]) + [""] * (len(columns) - len(r["values"]))
        body.append(f'<tr class="{cls}"><td>{e(r["metric"])}</td>' +
                    "".join(f"<td>{e(v) if v not in ('', None) else '–'}</td>" for v in vals) + "</tr>")
    return (f'<div class="sis-tablewrap"><table class="sis-table"><thead>{head}</thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def supplementary_table(items: list[dict], last_header: str = "Why it matters / how obtained") -> str:
    """Values taken from other websites, each with its source link."""
    head = "".join(f"<th>{e(h)}</th>" for h in ("Data point", "Value", "Period", "Source", last_header))
    body = []
    for it in items:
        if "analysts" in it:
            last = f"{it['analysts']} analysts" if it.get("analysts") else "analyst consensus"
        else:
            how = {"yfinance": "read by yfinance library", "NSE API": "read from NSE's official quote data",
                   "Value Research page": "read from its stock page"}.get(
                it.get("via")) or ("found by AI search" + ("" if it.get("seen_in_search") else ", page not confirmed"))
            last = "; ".join(x for x in [it.get("why"), how] if x)
        body.append(f'<tr><td>{e(it["metric"])}</td><td class="val">{e(it["value"])}</td>'
                    f'<td>{e(it.get("period") or "–")}</td>'
                    f'<td><a class="sis-src" href="{e(it.get("url") or "#")}" target="_blank">{e(it.get("source") or "source")} ↗</a></td>'
                    f'<td>{e(last)}</td></tr>')
    return (f'<div class="sis-tablewrap"><table class="sis-table wrap"><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def source_links(links: list[dict]) -> str:
    items = "".join(f'<li><a href="{e(l["url"])}" target="_blank">{e(l["site"])} ↗</a> '
                    f'<span class="d">{e(l.get("note", ""))}</span></li>' for l in links)
    return f'<div class="sis-card sis-doc"><h4>Connected websites</h4><ul>{items}</ul></div>'


# =====================================================================
# v2 builders (Value Research colours, Screener-like layout)
# =====================================================================
def fmt_money(v, nd: int = 2) -> str:
    from core.utils import fmt_num

    return "–" if v is None else f"₹{fmt_num(v, nd)}"


def company_header(payload: dict, company: dict, closes: dict | None = None) -> str:
    """Big company header: name, last price and change, BSE/NSE/website links, capture info."""
    m = payload.get("meta", {}) if payload else {}
    name = m.get("name") or company.get("name")
    price_html = ""
    c = closes or {}
    if c.get("close") is not None:
        chg = ""
        if c.get("prev_close"):
            pct = (c["close"] / c["prev_close"] - 1) * 100
            chg = f'<span class="chg {"up" if pct >= 0 else "dn"}">{"▲" if pct >= 0 else "▼"} {abs(pct):.2f}%</span>'
        d = c.get("trade_date")
        try:
            d = datetime.fromisoformat(str(d)[:10]).strftime("%d %b")
        except (TypeError, ValueError):
            pass
        price_html = (f'<div><span class="px">{e(fmt_money(c["close"], 2))}</span>{chg}'
                      f'<div class="asof">{e(d)} · close price (Screener)</div></div>')
    sym = m.get("nse_symbol") or company.get("nse_symbol")
    bse = m.get("bse_code") or company.get("bse_code")
    links = []
    if m.get("website"):
        site = str(m["website"]).replace("https://", "").replace("http://", "").strip("/")
        links.append(f'<a href="{e(m["website"])}" target="_blank">🔗 {e(site)}</a>')
    if bse:
        links.append(f'<span class="plain">BSE: {e(bse)}</span>')
    if sym:
        links.append(f'<a href="https://www.nseindia.com/get-quotes/equity?symbol={e(sym)}" target="_blank">NSE: {e(sym)} ↗</a>')
    if m.get("source_url"):
        links.append(f'<a href="{e(m["source_url"])}" target="_blank">Screener page ↗</a>')
    inds = "".join(f'<span class="ind">{e(x)}</span>' for x in [m.get("broad_industry"), m.get("industry")] if x)
    captured = m.get("captured_at", "")
    try:
        captured = datetime.fromisoformat(captured).strftime("%d %b %Y, %I:%M %p UTC")
    except (TypeError, ValueError):
        pass
    meta = (f'Screener data captured {e(captured)} · {e(m.get("basis", ""))} · latest period {e(m.get("latest_period") or "–")}'
            + (f' · next results {e(m["upcoming_result_date"])}' if m.get("upcoming_result_date") else "")) if m else \
        "No Screener data stored yet for this company."
    return f"""<div class="vr-co"><div class="row1"><span class="nm">{e(name)}</span>{price_html}</div>
      <div class="links">{''.join(links)}</div>
      <div class="meta">{inds}{meta}</div></div>"""


def ratio_box(payload: dict) -> str:
    """Screener's top ratio box: name on the left, value on the right, three per row."""
    cells = []
    for r in payload.get("summary_ratios", []):
        cells.append(f'<div class="c"><span class="n">{e(r["name"])}</span><span class="v">{e(r["value_text"])}</span></div>')
    rem = (-len(cells)) % 3
    cells += ['<div class="c"></div>'] * rem
    return f'<div class="vr-ratios">{"".join(cells)}</div>'


def pct_cell(v) -> str:
    if v is None:
        return "<td>–</td>"
    return f'<td class="{"up" if v >= 0 else "dn"}">{v:+.2f}%</td>'


def generic_table(columns: list[str], rows: list[list[str]], raw_html_cols: tuple[int, ...] = (),
                  cls: str = "") -> str:
    """rows are lists of display strings; columns listed in raw_html_cols are inserted as HTML (already safe)."""
    head = "".join(f"<th>{e(c)}</th>" for c in columns)
    body = []
    for r in rows:
        tds = []
        for i, v in enumerate(r):
            if i in raw_html_cols:
                tds.append(v if str(v).startswith("<td") else f"<td>{v}</td>")
            else:
                tds.append(f"<td>{e(v) if v not in ('', None) else '–'}</td>")
        body.append("<tr>" + "".join(tds) + "</tr>")
    return (f'<div class="sis-tablewrap"><table class="sis-table {cls}"><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')
