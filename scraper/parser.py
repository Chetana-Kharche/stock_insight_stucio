"""Parse a Screener.in company page into a normalized, JSON-serialisable document.

The output ("payload") is what we store in scrape_runs.payload, render in the UI,
export as JSON/PDF and flatten into financial_facts rows.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

from bs4 import BeautifulSoup, Tag

from core.config import PARSER_VERSION
from core.utils import clean_text, parse_number, period_to_date

FIN_SECTIONS = {
    "quarters": "Quarterly Results",
    "profit-loss": "Profit & Loss",
    "balance-sheet": "Balance Sheet",
    "cash-flow": "Cash Flows",
    "ratios": "Ratios",
}

_SCHEDULE_RE = re.compile(r"showSchedule\(\s*'([^']+)'\s*,\s*'([^']+)'")
_SHAREHOLDER_RE = re.compile(r"showShareholders\(\s*'([^']+)'\s*,\s*'([^']+)'")


# ----------------------------------------------------------------- units
def infer_unit(section: str, metric: str, value_text: str = "") -> str:
    m = metric.lower()
    if section.startswith("shareholding"):
        return "COUNT" if "no. of" in m else "PERCENT"
    if section == "growth":
        return "PERCENT"
    if "%" in metric or value_text.strip().endswith("%"):
        return "PERCENT"
    if "days" in m:
        return "DAYS"
    if m.startswith("eps") or "per share" in m:
        return "INR"
    if section == "ratios":
        return "RATIO"
    return "INR_CRORE"


def _summary_unit(name: str, value_text: str) -> str:
    n = name.lower()
    if "market cap" in n:
        return "INR_CRORE"
    if value_text.strip().endswith("%"):
        return "PERCENT"
    if "₹" in value_text or n in {"current price", "high / low", "book value", "face value"}:
        return "INR"
    return "RATIO"


def _metric_label(td: Tag) -> str:
    return clean_text(td.get_text(" ")).rstrip("+").strip()


# ----------------------------------------------------------------- tables
def parse_data_table(table: Tag, section: str) -> dict:
    """Parse a Screener 'data-table' (quarters / P&L / BS / CF / ratios / shareholding)."""
    columns: list[dict] = []
    thead = table.find("thead")
    header_cells = thead.find_all("th") if thead else []
    for th in header_cells[1:]:
        label = clean_text(th.get_text(" "))
        key = th.get("data-date-key") or ""
        if key and key.upper() != "TTM":
            pdate = period_to_date(key)
        else:
            pdate = period_to_date(label) if label.upper() != "TTM" else None
        ptype = "ttm" if label.upper() == "TTM" or key.upper() == "TTM" else (
            "quarter" if section in ("quarters", "shareholding-quarterly") else "annual")
        columns.append({"label": label, "date": pdate.isoformat() if pdate else None, "type": ptype})

    rows: list[dict] = []
    raw_pdfs: list[dict] = []
    body = table.find("tbody") or table
    for order, tr in enumerate(body.find_all("tr", recursive=False)):
        tds = tr.find_all("td", recursive=False)
        if not tds:
            continue
        metric = _metric_label(tds[0])
        if not metric:
            continue
        if metric.lower() == "raw pdf":
            for col, td in zip(columns, tds[1:]):
                a = td.find("a", href=True)
                if a:
                    raw_pdfs.append({"period": col["label"], "url": a["href"]})
            continue
        schedule_parent = None
        shareholder_class = None
        btn = tds[0].find("button")
        if btn and btn.get("onclick"):
            m = _SCHEDULE_RE.search(btn["onclick"])
            if m:
                schedule_parent = m.group(1)
            m2 = _SHAREHOLDER_RE.search(btn["onclick"])
            if m2:
                shareholder_class = m2.group(1)
        texts = [clean_text(td.get_text(" ")) for td in tds[1:]]
        texts += [""] * (len(columns) - len(texts))
        texts = texts[: len(columns)]
        rows.append({
            "metric": metric,
            "order": order,
            "values": texts,
            "numbers": [parse_number(t) for t in texts],
            "unit": infer_unit(section, metric, next((t for t in texts if t), "")),
            "is_bold": "strong" in (tr.get("class") or []),
            "schedule_parent": schedule_parent,
            "shareholder_class": shareholder_class,
            "schedules": {},     # filled by the client from the schedules API
        })
    out = {"columns": columns, "rows": rows}
    if raw_pdfs:
        out["raw_pdfs"] = raw_pdfs
    return out


def parse_ranges_tables(section: Tag) -> list[dict]:
    """Compounded Sales Growth / Profit Growth / Stock Price CAGR / Return on Equity."""
    out = []
    for t in section.select("table.ranges-table"):
        th = t.find("th")
        title = clean_text(th.get_text(" ")) if th else "Growth"
        items = []
        for tr in t.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) >= 2:
                vt = clean_text(tds[1].get_text(" "))
                items.append({"period": clean_text(tds[0].get_text(" ")).rstrip(":"),
                              "value_text": vt, "value": parse_number(vt)})
        out.append({"title": title, "rows": items})
    return out


def parse_peers_html(html: str) -> dict:
    """Parse the peers table returned by /api/company/<warehouse_id>/peers/."""
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    if not table:
        return {"columns": [], "rows": [], "median": None}
    trs = table.find_all("tr")
    if not trs:
        return {"columns": [], "rows": [], "median": None}
    columns = [clean_text(th.get_text(" ")) for th in trs[0].find_all("th")]
    rows, median = [], None
    for tr in trs[1:]:
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        cells = [clean_text(td.get_text(" ")) for td in tds]
        a = tds[1].find("a", href=True)
        rec = {
            "rank": parse_number(cells[0]) if cells[0] else None,
            "name": cells[1],
            "url": a["href"] if a else None,
            "values": dict(zip(columns[2:], cells[2:])),
            "numbers": {c: parse_number(v) for c, v in zip(columns[2:], cells[2:])},
        }
        if cells[1].lower().startswith("median"):
            median = rec
        else:
            rows.append(rec)
    return {"columns": columns, "rows": rows, "median": median}


# ----------------------------------------------------------------- documents
def _parse_documents(section: Optional[Tag]) -> dict:
    docs = {"announcements": [], "annual_reports": [], "credit_ratings": [], "concalls": []}
    if not section:
        return docs
    for block in section.select("div.documents"):
        h3 = block.find("h3")
        heading = clean_text(h3.get_text(" ")).lower() if h3 else ""
        classes = block.get("class") or []
        items = block.select("ul.list-links > li")
        if "concalls" in classes or heading.startswith("concall"):
            for li in items:
                period_div = li.find("div")
                links = {clean_text(a.get_text(" ")): a["href"] for a in li.find_all("a", href=True)}
                docs["concalls"].append({"period": clean_text(period_div.get_text(" ")) if period_div else "",
                                         "links": links})
        elif "annual-reports" in classes or heading.startswith("annual"):
            for li in items:
                a = li.find("a", href=True)
                if not a:
                    continue
                src = li.find("span")
                title = clean_text(a.get_text(" "))
                year = parse_number(title)
                docs["annual_reports"].append({"title": title, "url": a["href"],
                                               "year": int(year) if year else None,
                                               "source": clean_text(src.get_text(" ")) if src else ""})
        elif "credit-ratings" in classes or heading.startswith("credit"):
            for li in items:
                a = li.find("a", href=True)
                if not a:
                    continue
                meta = a.find("div")
                meta_text = clean_text(meta.get_text(" ")) if meta else ""
                if meta:
                    meta.extract()
                docs["credit_ratings"].append({"title": clean_text(a.get_text(" ")), "url": a["href"],
                                               "meta": meta_text})
        else:  # announcements
            for li in items:
                a = li.find("a", href=True)
                if not a:
                    continue
                t = a.find("time")
                when = t.get("datetime") if t else None
                meta = a.find("div")
                summary = ""
                if meta:
                    mt = clean_text(meta.get_text(" "))
                    summary = mt.split(" - ", 1)[1] if " - " in mt else ""
                    meta.extract()
                docs["announcements"].append({"title": clean_text(a.get_text(" ")), "url": a["href"],
                                              "date": when, "summary": summary})
    return docs


# ----------------------------------------------------------------- main
def parse_company_page(html: str, source_url: str, requested_basis: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    info = soup.find(id="company-info")
    if info is None:
        raise ValueError("This does not look like a Screener company page (company-info block missing).")

    h1 = soup.find("h1")
    name = ""
    if h1:
        spans = [clean_text(s.get_text(" ")) for s in h1.find_all("span")]
        spans = [s for s in spans if s]
        name = spans[-1] if spans else clean_text(h1.get_text(" "))

    consolidated = (info.get("data-consolidated") or "").lower() == "true"
    meta: dict[str, Any] = {
        "name": name,
        "source_url": source_url,
        "requested_basis": requested_basis,
        "basis": "consolidated" if consolidated else "standalone",
        "screener_company_id": int(info["data-company-id"]) if info.get("data-company-id") else None,
        "screener_warehouse_id": int(info["data-warehouse-id"]) if info.get("data-warehouse-id") else None,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "parser_version": PARSER_VERSION,
    }

    # --- links (website / BSE / NSE)
    profile = soup.select_one(".company-profile") or soup
    for a in profile.find_all("a", href=True):
        href, txt = a["href"], clean_text(a.get_text(" ")).upper()
        if txt == "WEBSITE":
            meta["website"] = href
        elif "bseindia.com/stock-share-price" in href:
            m = re.search(r"/(\d{6})/?", href)
            if m:
                meta["bse_code"] = m.group(1)
        elif "nseindia.com/get-quotes/equity" in href:
            m = re.search(r"symbol=([^&]+)", href)
            if m:
                meta["nse_symbol"] = m.group(1)

    about_el = soup.select_one(".company-profile .about")
    about = ""
    if about_el:
        for sup in about_el.find_all("sup"):
            sup.decompose()
        about = clean_text(about_el.get_text(" "))

    # --- sector classification from peers header
    peers_sec = soup.find(id="peers")
    if peers_sec:
        for a in peers_sec.select("p.sub a[title]"):
            key = {"Broad Sector": "broad_sector", "Sector": "sector",
                   "Broad Industry": "broad_industry", "Industry": "industry"}.get(a["title"])
            if key:
                meta[key] = clean_text(a.get_text(" "))
        meta["indices"] = [clean_text(a.get_text(" ")) for a in peers_sec.select("#benchmarks a.tag")]

    # --- summary ratios
    summary = []
    for li in soup.select("#top-ratios li"):
        n = li.select_one(".name")
        v = li.select_one(".value")
        if not n:
            continue
        nums = [parse_number(s.get_text()) for s in li.select(".number")]
        vt = clean_text(v.get_text(" ")) if v else ""
        nm = clean_text(n.get_text(" "))
        summary.append({"name": nm, "value": nums[0] if nums else None,
                        "value2": nums[1] if len(nums) > 1 else None,
                        "value_text": vt, "unit": _summary_unit(nm, vt)})

    # --- pros / cons
    pros = [clean_text(li.get_text(" ")) for li in soup.select("#analysis .pros li")]
    cons = [clean_text(li.get_text(" ")) for li in soup.select("#analysis .cons li")]

    # --- financial sections
    sections: dict[str, dict] = {}
    for sid, title in FIN_SECTIONS.items():
        sec = soup.find("section", id=sid)
        if not sec:
            continue
        table = sec.select_one("table.data-table")
        if not table:
            continue
        parsed = parse_data_table(table, sid)
        sub = sec.select_one("p.sub")
        parsed["title"] = title
        parsed["note"] = clean_text(sub.get_text(" ")).replace("View Standalone", "").replace(
            "View Consolidated", "").strip(" /") if sub else ""
        sections[sid] = parsed

    growth = []
    pl = soup.find("section", id="profit-loss")
    if pl:
        growth = parse_ranges_tables(pl)

    shareholding = {}
    shp = soup.find("section", id="shareholding")
    if shp:
        for key, div_id in (("quarterly", "quarterly-shp"), ("yearly", "yearly-shp")):
            div = shp.find(id=div_id)
            table = div.find("table") if div else None
            if table:
                shareholding[key] = parse_data_table(table, f"shareholding-{key}")
        note = shp.select_one(".sub")
        if note:
            shareholding["note"] = clean_text(note.get_text(" "))

    upcoming = None
    for badge in soup.select("#quarters .badge"):
        t = clean_text(badge.get_text(" "))
        if "result date" in t.lower():
            upcoming = t.split(":", 1)[-1].strip()

    documents = _parse_documents(soup.find("section", id="documents"))

    latest_period = None
    q = sections.get("quarters")
    if q and q["columns"]:
        latest_period = q["columns"][-1]["date"]
    meta["latest_period"] = latest_period
    meta["upcoming_result_date"] = upcoming

    return {
        "meta": meta,
        "about": about,
        "pros": pros,
        "cons": cons,
        "summary_ratios": summary,
        "peers": {"columns": [], "rows": [], "median": None},
        "sections": sections,
        "growth": growth,
        "shareholding": shareholding,
        "documents": documents,
        "price_history": [],
        "pe_history": {},
    }
