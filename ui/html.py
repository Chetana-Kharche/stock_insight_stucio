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
    blocks = []
    for g in growth:
        rows = "".join(f"<tr><td>{e(it['period'])}</td><td>{e(it['value_text'])}</td></tr>" for it in g["rows"])
        blocks.append(f"""<div><div class="sis-sub" style="font-weight:700;text-transform:uppercase">{e(g['title'])}</div>
            <div class="sis-tablewrap"><table class="sis-table"><thead><tr><th>Metric</th><th>Value</th></tr></thead>
            <tbody>{rows}</tbody></table></div></div>""")
    return f'<div class="sis-grid" style="grid-template-columns:repeat(4,minmax(0,1fr))">{"".join(blocks)}</div>'


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
            how = "read by yfinance library" if it.get("via") == "yfinance" else (
                "found by AI search" + ("" if it.get("seen_in_search") else ", page not confirmed"))
            last = "; ".join(x for x in [it.get("why"), how] if x)
        body.append(f'<tr><td>{e(it["metric"])}</td><td class="val">{e(it["value"])}</td>'
                    f'<td>{e(it.get("period") or "–")}</td>'
                    f'<td><a class="sis-src" href="{e(it.get("url") or "#")}" target="_blank">{e(it["source"])} ↗</a></td>'
                    f'<td>{e(last)}</td></tr>')
    return (f'<div class="sis-tablewrap"><table class="sis-table wrap"><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def source_links(links: list[dict]) -> str:
    items = "".join(f'<li><a href="{e(l["url"])}" target="_blank">{e(l["site"])} ↗</a> '
                    f'<span class="d">{e(l.get("note", ""))}</span></li>' for l in links)
    return f'<div class="sis-card sis-doc"><h4>Connected websites</h4><ul>{items}</ul></div>'
