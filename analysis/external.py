"""Supplementary data from other websites, used ONLY while building the analysis report.

Screener.in stays the main source: the scrape, the stored facts, the scorecard and every table come
from Screener alone.  This module fills gaps (figures Screener does not publish) and adds a few extra
data points that matter for analysis, from:

    NSE                    - official quote API (sector P/E, delivery %, free float ...)
    Value Research Online  - its public stock page read directly (analysis/valueresearch.py):
                             VR quality/growth/valuation/momentum scores, industry P/E, EV/EBITDA, returns vs Sensex
    Yahoo Finance          - structured fields through the `yfinance` library
    Investing.com, Macrotrends (and Value Research for anything else) - looked up by Gemini with Google Search,
                             restricted to these sites

Rules:
  * a field is taken only if Screener does not already provide it;
  * every value carries its source name and link, and is shown in its own section of the report;
  * nothing from here changes the scorecard or the stored Screener data;
  * every call is best-effort - if a site or the AI lookup fails, the report is still produced.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote_plus, urlparse

from analysis import llm
from analysis.news import short_name
from core.config import get_settings
from core.utils import fmt_num

log = logging.getLogger(__name__)

CACHE_VERSION = 5   # bump when the lookup changes, so old cached lookups are not reused

SITE_NAMES = {
    "nseindia.com": "NSE",
    "finance.yahoo.com": "Yahoo Finance",
    "valueresearchonline.com": "Value Research Online",
    "investing.com": "Investing.com",
    "macrotrends.net": "Macrotrends",
}

# (yfinance info key, label, kind) - only items Screener does NOT show.
# Promoter / FII / DII holding, debt, sales, profit, P/E, ROE etc. are deliberately absent: Screener has them.
YAHOO_FIELDS = [
    ("beta", "Beta (share price volatility vs market)", "x"),
    ("forwardPE", "Forward P/E (on analysts' next-year earnings)", "x"),
    ("forwardEps", "Forward EPS, analysts' estimate", "inr"),
    ("trailingPegRatio", "PEG ratio", "x"),
    ("priceToSalesTrailing12Months", "Price to sales", "x"),
    ("enterpriseValue", "Enterprise value", "crore"),
    ("returnOnAssets", "Return on assets", "pct_fraction"),
    ("sharesOutstanding", "Shares outstanding", "crore_count"),
    ("floatShares", "Free-float shares", "crore_count"),
    ("averageVolume", "Average daily volume (shares)", "count"),
    ("targetMeanPrice", "Analysts' average target price (third-party view)", "inr"),
    ("targetHighPrice", "Analysts' highest target price (third-party view)", "inr"),
    ("targetLowPrice", "Analysts' lowest target price (third-party view)", "inr"),
    ("numberOfAnalystOpinions", "Number of analysts covering", "count"),
    ("recommendationKey", "Analysts' consensus rating (third-party view)", "text"),
    ("totalCash", "Cash and equivalents", "crore"),
    ("fullTimeEmployees", "Employees", "count"),
    ("overallRisk", "ISS governance risk score (1 low - 10 high)", "count"),
]

BANK_GAPS = ["Net interest margin (NIM)", "Gross NPA %", "Net NPA %", "CASA ratio", "Capital adequacy ratio (CRAR)",
             "Cost-to-income ratio", "Provision coverage ratio", "Credit-deposit ratio", "Loan (advances) growth YoY",
             "Deposit growth YoY"]
GENERAL_GAPS = ["Promoter pledged shares %", "Interest coverage ratio", "Analysts' consensus target price",
                "Next fiscal year EPS estimate (consensus)", "Beta", "Fair value / valuation rating shown by the site"]


# ------------------------------------------------------------------ links
def source_links(company_name: str, nse_symbol: Optional[str], bse_code: Optional[str] = None) -> list[dict]:
    """Links a reader can open for each connected website (direct page where the URL is predictable)."""
    q = quote_plus(short_name(company_name or nse_symbol or ""))
    sym = (nse_symbol or "").upper()
    links = []
    if sym:
        links.append({"site": "NSE", "url": f"https://www.nseindia.com/get-quotes/equity?symbol={sym}",
                      "note": "official quote, delivery %, sector P/E, filings"})
    if sym:
        links.append({"site": "Yahoo Finance", "url": f"https://finance.yahoo.com/quote/{sym}.NS/",
                      "note": "quote, analyst estimates, statistics"})
    elif bse_code:
        links.append({"site": "Yahoo Finance", "url": f"https://finance.yahoo.com/quote/{bse_code}.BO/",
                      "note": "quote, analyst estimates, statistics"})
    links.append({"site": "Value Research Online",
                  "url": f"https://www.google.com/search?q=site%3Avalueresearchonline.com%2Fstocks+{q}",
                  "note": "stock page, ratings, shareholding"})
    links.append({"site": "Investing.com", "url": f"https://www.investing.com/search/?q={quote_plus(sym or q)}",
                  "note": "financial summary, ratios, technicals"})
    links.append({"site": "Macrotrends",
                  "url": f"https://www.google.com/search?q=site%3Amacrotrends.net+{q}",
                  "note": "long-term charts (mainly companies with a US listing)"})
    return links


# ------------------------------------------------------------------ Yahoo Finance
def _fmt(value: Any, kind: str) -> Optional[str]:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    try:
        if kind == "x":
            return f"{float(value):.2f}x"
        if kind == "inr":
            return f"₹{fmt_num(float(value), 2)}"
        if kind == "pct_fraction":
            return f"{float(value) * 100:.2f}%"
        if kind == "crore":
            return f"₹{fmt_num(float(value) / 1e7)} crore"
        if kind == "crore_count":
            return f"{fmt_num(float(value) / 1e7, 2)} crore"
        if kind == "count":
            return fmt_num(float(value))
    except (TypeError, ValueError):
        return None
    return str(value)


NOT_FOR_LENDERS = {"enterpriseValue", "totalCash", "priceToSalesTrailing12Months"}  # not meaningful for banks
MONEY_KINDS = {"inr", "crore"}


def fetch_yahoo(nse_symbol: Optional[str], bse_code: Optional[str] = None, is_lender: bool = False) -> dict:
    """Return {"ticker", "url", "items": [...], "estimates": [...]} or {"error": ...}."""
    try:
        import yfinance as yf
    except ImportError:
        return {"error": "yfinance is not installed (pip install yfinance)"}
    candidates = ([f"{nse_symbol.upper()}.NS"] if nse_symbol else []) + ([f"{bse_code}.BO"] if bse_code else [])
    info, ticker, tk = {}, None, None
    for tk in candidates:
        try:
            ticker = yf.Ticker(tk)
            info = ticker.info or {}
            if info.get("marketCap") or info.get("currentPrice") or info.get("regularMarketPrice"):
                break
            info = {}
        except Exception as e:  # noqa: BLE001 - rate limits, delisted, network
            log.warning("Yahoo Finance %s failed: %s", tk, e)
            info = {}
    if not info:
        return {"error": "Yahoo Finance returned no data (rate limit, network or unknown ticker)"}
    url = f"https://finance.yahoo.com/quote/{tk}/"
    items = []
    in_rupees = (info.get("financialCurrency") or info.get("currency") or "INR").upper() == "INR"
    for key, label, kind in YAHOO_FIELDS:
        if (is_lender and key in NOT_FOR_LENDERS) or (kind in MONEY_KINDS and not in_rupees):
            continue
        text = _fmt(info.get(key), kind)
        if text:
            items.append({"metric": label, "value": text, "raw": info.get(key), "period": "latest",
                          "source": "Yahoo Finance", "url": url, "via": "yfinance"})
    estimates = []
    for attr, label in (("earnings_estimate", "EPS estimate"), ("revenue_estimate", "Revenue estimate")):
        try:
            df = getattr(ticker, attr)
            if df is None or getattr(df, "empty", True):
                continue
            for period, row in df.iterrows():
                avg = row.get("avg")
                if avg is None or (isinstance(avg, float) and math.isnan(avg)):
                    continue
                n = row.get("numberOfAnalysts")
                if not in_rupees:
                    continue
                pretty = (f"₹{fmt_num(float(avg), 2)}" if attr == "earnings_estimate"
                          else f"₹{fmt_num(float(avg) / 1e7)} crore")
                rng = ""
                if row.get("low") is not None and row.get("high") is not None and attr == "earnings_estimate":
                    rng = f" (range ₹{fmt_num(float(row['low']), 2)} to ₹{fmt_num(float(row['high']), 2)})"
                estimates.append({
                    "metric": f"Analysts' {label}", "value": pretty + rng,
                    "period": {"0q": "current quarter", "+1q": "next quarter", "0y": "current fiscal year",
                               "+1y": "next fiscal year"}.get(str(period), str(period)),
                    "analysts": None if n is None or (isinstance(n, float) and math.isnan(n)) else int(n),
                    "source": "Yahoo Finance", "url": url + "analysis/", "via": "yfinance"})
        except Exception:  # noqa: BLE001 - estimates are optional
            continue
    return {"ticker": tk, "url": url, "items": items, "estimates": estimates}


# ------------------------------------------------------------------ NSE (official exchange data)
def _g(d: Any, *path: str) -> Any:
    for k in path:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def fetch_nse(nse_symbol: Optional[str]) -> dict:
    """Exchange-level facts Screener does not show, from NSE's quote API: sector P/E, delivery %, free float,
    impact cost, margin rate, price band, 52-week high/low dates, F&O status, NSE industry classification."""
    if not nse_symbol:
        return {"error": "no NSE symbol"}
    from analysis.market import _nse_session

    sym = quote_plus(nse_symbol.upper())
    url = f"https://www.nseindia.com/get-quotes/equity?symbol={sym}"
    import time

    q, t, last = None, {}, "no answer"
    for attempt in range(3):          # NSE needs fresh cookies from its web pages and sometimes refuses the first try
        try:
            sess = _nse_session()
            sess.headers["Referer"] = url
            try:
                sess.get(url, timeout=12)  # the quote page sets the cookies the API checks
            except Exception:  # noqa: BLE001
                pass
            r = sess.get(f"https://www.nseindia.com/api/quote-equity?symbol={sym}", timeout=12)
            if r.status_code != 200 or not r.text.strip().startswith("{"):
                last = f"HTTP {r.status_code}"
                time.sleep(1.5 * (attempt + 1))
                continue
            q = r.json()
            try:
                tr = sess.get(f"https://www.nseindia.com/api/quote-equity?symbol={sym}&section=trade_info", timeout=12)
                t = tr.json() if tr.ok and tr.text.strip().startswith("{") else {}
            except Exception:  # noqa: BLE001
                t = {}
            break
        except Exception as e:  # noqa: BLE001 - NSE often blocks scripts
            last = type(e).__name__
            time.sleep(1.5 * (attempt + 1))
    if q is None:
        return {"error": f"NSE did not answer ({last}); NSE often blocks automated requests, try again later"}

    items: list[dict] = []

    def add(metric: str, value: Any, period: str = "latest", why: str = "", fmt: str = "{}") -> None:
        if value in (None, "", "-", "NA"):
            return
        try:
            text = fmt.format(float(value)) if fmt != "{}" else str(value)
        except (TypeError, ValueError):
            text = str(value)
        items.append({"metric": metric, "value": text, "period": period, "source": "NSE", "url": url,
                      "via": "NSE API", "why": why})

    sector_pe = _g(q, "metadata", "pdSectorPe")
    add("Sector P/E (" + str(_g(q, "metadata", "pdSectorInd") or "sector index").strip() + ")", sector_pe,
        why="compare the company's P/E with its sector", fmt="{:.2f}x")
    add("Delivery as % of traded quantity", _g(t, "securityWiseDP", "deliveryToTradedQuantity"),
        period=str(_g(t, "securityWiseDP", "secWiseDelPosDate") or "latest session"),
        why="share of trades held, not intraday", fmt="{:.2f}%")
    ffmc, tmc = _g(t, "marketDeptOrderBook", "tradeInfo", "ffmc"), _g(t, "marketDeptOrderBook", "tradeInfo", "totalMarketCap")
    try:
        if ffmc and tmc and float(tmc) > 0:
            add("Free-float as % of market cap", float(ffmc) / float(tmc) * 100,
                why="shares available for public trading", fmt="{:.1f}%")
    except (TypeError, ValueError):
        pass
    add("Impact cost", _g(t, "marketDeptOrderBook", "tradeInfo", "impactCost"), why="liquidity: lower is better",
        fmt="{:.2f}%")
    add("Margin rate (applicable margin)", _g(t, "marketDeptOrderBook", "valueAtRisk", "applicableMargin"),
        why="exchange's view of price risk", fmt="{:.2f}%")
    band = _g(q, "priceInfo", "pPriceBand")
    add("Daily price band", band if band in (None, "", "No Band") else f"{band}%", why="maximum daily move allowed")
    hi, hid = _g(q, "priceInfo", "weekHighLow", "max"), _g(q, "priceInfo", "weekHighLow", "maxDate")
    lo, lod = _g(q, "priceInfo", "weekHighLow", "min"), _g(q, "priceInfo", "weekHighLow", "minDate")
    if hi and hid:
        add("52-week high (date)", f"₹{fmt_num(float(hi), 2)} on {hid}", why="when the peak was reached")
    if lo and lod:
        add("52-week low (date)", f"₹{fmt_num(float(lo), 2)} on {lod}", why="when the low was reached")
    fno = _g(q, "info", "isFNOSec")
    if fno is not None:
        add("In futures & options segment", "Yes" if fno else "No", why="derivatives trading allowed")
    basic = _g(q, "industryInfo", "basicIndustry")
    if basic:
        add("NSE industry classification", " › ".join(dict.fromkeys(x for x in [_g(q, "industryInfo", "macro"),
                                                                               _g(q, "industryInfo", "sector"), basic] if x)),
            why="official sector grouping")
    return {"items": items, "url": url}


# ------------------------------------------------------------------ gap list
def find_gaps(payload: dict, metrics: dict, yahoo_items: list[dict]) -> list[str]:
    """Things Screener (and Yahoo, if it answered) did not give us, worth looking up elsewhere."""
    gaps: list[str] = []
    is_fin = metrics.get("company_type") == "bank_or_nbfc"
    if is_fin:
        gaps += BANK_GAPS
    have = " | ".join(i["metric"].lower() for i in yahoo_items)
    for g in GENERAL_GAPS:
        key = g.lower().split(" (")[0]
        if key.startswith("beta") and "beta" in have:
            continue
        if "target price" in key and "target price" in have:
            continue
        if "eps estimate" in key and "forward eps" in have:
            continue
        if is_fin and key.startswith("interest coverage"):
            continue
        gaps.append(g)
    if metrics.get("profitability", {}).get("roce_current") is None and not is_fin:
        gaps.append("Return on capital employed (ROCE)")
    if not (metrics.get("cash_flow") or {}).get("cfo_latest") and not is_fin:
        gaps.append("Operating cash flow, latest fiscal year")
    if not metrics.get("valuation", {}).get("median_pe_5y"):
        gaps.append("5-year average or median P/E")
    return gaps


# ------------------------------------------------------------------ AI lookup (Gemini + Google Search)
def _domain(url_or_text: str) -> str:
    t = (url_or_text or "").strip().lower()
    if "://" in t:
        t = urlparse(t).netloc
    return t.removeprefix("www.")


def _allowed(domain: str, sites: tuple) -> Optional[str]:
    """Match a domain ('www.investing.com') or a site name ('Value Research Online') to an allowed site."""
    squashed = "".join(ch for ch in domain.lower() if ch.isalnum())
    for s in sites:
        if domain == s or domain.endswith("." + s) or s.endswith("." + domain):
            return s
        label = s.split(".")[-2] if "." in s else s          # finance.yahoo.com -> yahoo
        if "." not in domain and len(label) >= 5 and label in squashed:
            return s
    return None


def ai_lookup(company: dict, gaps: list[str], already_have: list[str], sites: tuple, strict: bool = True) -> dict:
    """Ask Gemini (with Google Search) for the missing items, restricted to the configured websites.

    strict=True keeps a value only when its website is among the pages Google Search actually returned for
    this request, so a figure the model merely "remembers" is never shown as sourced data.
    """
    if not llm.is_available():
        return {"items": [], "error": "Gemini is not configured"}
    if not gaps:
        return {"items": []}
    name, sym = company.get("name") or "", company.get("nse_symbol") or ""
    prompt = (
        f"Company: {name} (NSE: {sym}, India). Industry: {company.get('industry') or company.get('broad_industry') or ''}.\n"
        f"Find the LATEST published value for each item in ITEMS. Use ONLY these websites as sources: "
        f"{', '.join(sites)}. Search with queries such as \"{name} site:{sites[0]}\" and "
        f"\"{sym} {sites[0]}\". Do NOT use screener.in. For each value give the period it refers to and the exact "
        f"page URL. If an item is not shown on these websites, leave it out - never estimate or guess. "
        f"You may add up to 3 extra data points from these websites that you judge important for analysing this "
        f"company and that are not in ALREADY_HAVE.\n\n"
        f"ITEMS: {gaps}\n\nALREADY_HAVE (do not repeat): {already_have}\n\n"
        'Reply with ONLY a JSON object, no other text: {"items": [{"metric": "...", "value": "... with unit", '
        '"period": "e.g. Q1 FY27 or FY26 or as of date", "source": "website domain", "url": "https://...", '
        '"why_it_matters": "max 15 words"}]}'
    )
    try:
        out = llm.generate_grounded(
            prompt, system="You are a careful financial data researcher. Report only figures you actually found on "
                           "the allowed websites, with their source. Accuracy matters more than coverage.")
        data = llm.extract_json(out["text"])
    except Exception as e:  # noqa: BLE001
        log.warning("AI lookup failed: %s", e)
        return {"items": [], "error": f"{type(e).__name__}: {e}"}

    searched = {_domain(s.get("title") or "") for s in out.get("sources", [])} | \
               {_domain(s.get("url") or "") for s in out.get("sources", [])}
    items, dropped, unconfirmed = [], 0, 0
    for it in (data.get("items") or [])[:20]:
        if not isinstance(it, dict) or not it.get("metric") or not it.get("value"):
            continue
        dom = _allowed(_domain(str(it.get("url") or "")), sites) or _allowed(_domain(str(it.get("source") or "")), sites)
        if not dom:
            dropped += 1
            continue
        url = str(it.get("url") or "")
        if not url.startswith("http") or not _allowed(_domain(url), sites):
            url = f"https://www.{dom}/"
        seen = any(_allowed(d, (dom,)) for d in searched if d)
        if strict and not seen:
            unconfirmed += 1
            continue
        items.append({
            "metric": str(it["metric"])[:120], "value": str(it["value"])[:80], "period": str(it.get("period") or "")[:40],
            "source": SITE_NAMES.get(dom, dom), "url": url, "why": str(it.get("why_it_matters") or "")[:120],
            "via": "AI search", "seen_in_search": seen,
        })
    return {"items": items, "dropped_other_sites": dropped, "dropped_unconfirmed": unconfirmed,
            "queries": out.get("queries", [])[:8]}


def ai_lookup_per_site(company: dict, gaps: list[str], already_have: list[str], sites: tuple,
                       strict: bool = True) -> dict:
    """One search per website (in parallel), so each site gets its own chance instead of one mixed query."""
    from concurrent.futures import ThreadPoolExecutor

    ai_sites = [x for x in sites if "yahoo" not in x and "nseindia" not in x]
    if not ai_sites:
        return {"items": [], "per_site": {}}
    with ThreadPoolExecutor(max_workers=len(ai_sites)) as ex:
        results = dict(zip(ai_sites, ex.map(lambda site: ai_lookup(company, gaps, already_have, (site,), strict),
                                            ai_sites)))
    items, notes, dropped_other, dropped_unconf = [], [], 0, 0
    seen = {m.lower() for m in already_have}
    for site, r in results.items():
        name = SITE_NAMES.get(site, site)
        if r.get("error"):
            notes.append(f"{name}: {r['error'][:140]}")
        got = 0
        for it in r.get("items", []):
            key = it["metric"].lower()
            if key in seen:
                continue
            seen.add(key)
            items.append(it)
            got += 1
        dropped_other += r.get("dropped_other_sites", 0)
        dropped_unconf += r.get("dropped_unconfirmed", 0)
        if not r.get("error"):
            notes.append(f"{name}: {got} value(s) found" + (
                f", {r.get('dropped_unconfirmed', 0)} discarded (page not in search results)"
                if r.get("dropped_unconfirmed") else ""))
    return {"items": items, "notes": notes, "dropped_other_sites": dropped_other, "dropped_unconfirmed": dropped_unconf}


# ------------------------------------------------------------------ main entry
def collect_supplementary(payload: dict, metrics: dict, use_ai: bool = True, company_id: Optional[int] = None) -> dict:
    """Gather supplementary data for one company: Yahoo Finance + NSE + (AI search of) Value Research,
    Investing.com and Macrotrends. Only figures Screener does not show. Never raises."""
    from concurrent.futures import ThreadPoolExecutor

    s = get_settings()
    meta = payload.get("meta", {})
    company = {k: meta.get(k) for k in ("name", "nse_symbol", "bse_code", "industry", "broad_industry")}
    out: dict = {"version": CACHE_VERSION, "enabled": s.external_enabled,
                 "fetched_at": datetime.now(timezone.utc).isoformat(),
                 "links": source_links(company["name"], company["nse_symbol"], company["bse_code"]),
                 "items": [], "estimates": [], "notes": []}
    if not s.external_enabled:
        out["notes"].append("Supplementary sources are switched off (EXTERNAL_SOURCES_ENABLED=false).")
        return out

    lender = metrics.get("company_type") == "bank_or_nbfc"
    from analysis.valueresearch import fetch_valueresearch

    with ThreadPoolExecutor(max_workers=3) as ex:
        fy = ex.submit(fetch_yahoo, company["nse_symbol"], company["bse_code"], lender) \
            if any("yahoo" in d for d in s.external_sites) else None
        fn = ex.submit(fetch_nse, company["nse_symbol"])
        fv = ex.submit(fetch_valueresearch, company["name"] or "", company["nse_symbol"], company["bse_code"],
                       company_id) if any("valueresearch" in d for d in s.external_sites) else None
        y = _safe_result(fy)
        n = _safe_result(fn)
        v = _safe_result(fv)

    direct: list[dict] = []
    if v is not None:
        if v.get("items"):
            direct += v["items"]
            out["notes"].append(f"Value Research Online: {len(v['items'])} value(s) read from its stock page "
                                f"({v.get('how')})")
            for ln in out["links"]:
                if ln["site"] == "Value Research Online":
                    ln["url"], ln["note"] = v["url"], "stock page: VR rating scores, returns, valuation"
        else:
            out["notes"].append(f"Value Research Online page: {v.get('error')}")
    if y is not None:
        if y.get("error"):
            out["notes"].append(f"Yahoo Finance: {y['error']}")
        else:
            direct += y["items"]
            out["estimates"] += y["estimates"]
            out["notes"].append(f"Yahoo Finance: {len(y['items'])} value(s) read")
    if n.get("error"):
        out["notes"].append(f"NSE: {n['error']}")
    else:
        direct += n["items"]
        out["notes"].append(f"NSE: {len(n['items'])} value(s) read")
    out["items"] += direct

    if use_ai:
        gaps = find_gaps(payload, metrics, direct)
        out["gaps_requested"] = gaps
        have = [r["name"] for r in payload.get("summary_ratios", [])] + [i["metric"] for i in direct]
        try:
            ai = ai_lookup_per_site(company, gaps, have, s.external_sites, strict=s.external_strict)
        except Exception as e:  # noqa: BLE001
            ai = {"items": [], "notes": [f"AI search: {type(e).__name__}: {e}"]}
        out["items"] += ai.get("items", [])
        out["notes"] += ai.get("notes", [])
        if ai.get("dropped_other_sites"):
            out["notes"].append(f"{ai['dropped_other_sites']} value(s) from websites outside the approved list "
                                f"were discarded.")
    else:
        out["notes"].append("Value Research / Investing.com / Macrotrends need Gemini (AI search); not used.")
    # list the sources in a fixed order: NSE, Value Research, Investing.com, Macrotrends, Yahoo Finance
    order = {"NSE": 0, "Value Research Online": 1, "Investing.com": 2, "Macrotrends": 3, "Yahoo Finance": 4}
    out["items"].sort(key=lambda i: order.get(i.get("source"), 9))
    out["sources_used"] = sorted({i["source"] for i in out["items"] + out["estimates"]}, key=lambda x: order.get(x, 9))
    if not out["items"] and not out["estimates"]:
        out["notes"].append("No supplementary values could be retrieved this time; the links below still work.")
    return out


def _safe_result(fut) -> Optional[dict]:
    if fut is None:
        return None
    try:
        return fut.result()
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


def get_supplementary(payload: dict, metrics: dict, company_id: Optional[int], use_ai: bool = True,
                      max_age_hours: float = 24, force: bool = False) -> dict:
    """Cached version of collect_supplementary(): reuse a lookup younger than `max_age_hours`.

    The result is stored in the external_data table, separate from the Screener tables.
    """
    from core import repository as repo

    if company_id and not force:
        try:
            cached = repo.latest_external(company_id, max_age_hours)
            if cached and cached.get("version") == CACHE_VERSION and (cached.get("items") or cached.get("estimates")):
                cached["from_cache"] = True
                return cached
        except Exception as e:  # noqa: BLE001 - table missing (migration not run) or DB issue
            log.warning("external_data cache unavailable: %s", e)
    out = collect_supplementary(payload, metrics, use_ai=use_ai, company_id=company_id)
    if company_id and (out.get("items") or out.get("estimates")):
        try:
            repo.save_external(company_id, out)
        except Exception as e:  # noqa: BLE001
            log.warning("Could not store external data: %s", e)
    return out
