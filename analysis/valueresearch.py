"""Value Research Online (valueresearchonline.com) - read the company's public stock page directly.

What it adds to the report (all things Screener does not publish):
  * Value Research stock rating scores: Quality, Growth, Valuation, Momentum (each out of 10)
  * Industry P/E, EV/EBITDA, P/B, liquidity rating
  * peer-median P/E and P/B (from the page's FAQ text)
  * share-price returns (1Y / 3Y / 5Y / 10Y) next to the BSE Sensex and the sector index
  * year-end P/E and P/B history

How the page is found (cached in the company_links table, so this happens once per company):
  1. a saved link (found earlier, or pasted by the user on the Key Ratios tab)
  2. DuckDuckGo / Bing web search restricted to valueresearchonline.com/stocks
  3. Gemini with Google Search (if configured)
Every candidate page is opened and accepted only if it shows the company's NSE symbol or BSE code.

The page layout is read as plain text (label -> next value) and with pandas.read_html for its tables, so small
layout changes do not break it. Anything that fails is skipped; the report is still produced.
"""
from __future__ import annotations

import io
import logging
import re
from typing import Any, Optional
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import requests

from analysis.news import HEADERS, short_name
from core.utils import clean_text

log = logging.getLogger(__name__)

SITE = "Value Research Online"
STOCK_URL_RX = re.compile(r"https?://(?:www\.)?valueresearchonline\.com/stocks/(\d+)/([a-z0-9\-]+)/?", re.I)
_NUM = r"-?[\d,]*\.?\d+"

# label on the page -> (label in the report, why it matters, kind)
LABELS = [
    ("Quality Score", "Value Research quality score", "business quality as rated by Value Research", "score"),
    ("Growth Score", "Value Research growth score", "growth record as rated by Value Research", "score"),
    ("Valuation Score", "Value Research valuation score", "higher = cheaper relative to its own record", "score"),
    ("Momentum Score", "Value Research momentum score", "recent price strength", "score"),
    ("Industry P/E", "Industry P/E", "compare the company's P/E with its industry", "x"),
    ("EV/EBITDA", "EV/EBITDA", "valuation including debt", "x"),
    ("P/B Ratio", "Price to book (P/B)", "price compared with book value", "x"),
    ("Liquidity", "Liquidity rating", "how easily the share trades", "word"),
]


# ------------------------------------------------------------------ fetching
def _get(url: str, timeout: int = 15) -> str:
    r = requests.get(url, headers={**HEADERS, "Accept-Language": "en-IN,en;q=0.9"}, timeout=timeout)
    r.raise_for_status()
    return r.text


def _canonical(url: str) -> Optional[str]:
    m = STOCK_URL_RX.search(url or "")
    return f"https://www.valueresearchonline.com/stocks/{m.group(1)}/{m.group(2).lower()}/" if m else None


def _search_urls(html: str) -> list[str]:
    """Value Research stock URLs inside a search-results page (handles DuckDuckGo's redirect links)."""
    found = []
    for href in re.findall(r'href="([^"]+)"', html):
        if "uddg=" in href:
            href = unquote(parse_qs(urlparse(href).query).get("uddg", [""])[0])
        c = _canonical(unquote(href))
        if c and c not in found:
            found.append(c)
    for raw in STOCK_URL_RX.finditer(unquote(html)):      # plain or URL-encoded links (Bing, Yahoo redirect links)
        c = _canonical(raw.group(0))
        if c and c not in found:
            found.append(c)
    # breadcrumb form shown by search engines: "valueresearchonline.com › stocks › 42383 › wipro-ltd"
    for m in re.finditer(r"valueresearchonline\.com\s*(?:›|&rsaquo;|/)\s*stocks\s*(?:›|&rsaquo;|/)\s*(\d+)\s*"
                         r"(?:›|&rsaquo;|/)\s*([a-z0-9\-]+)", html, re.I):
        c = f"https://www.valueresearchonline.com/stocks/{m.group(1)}/{m.group(2).lower()}/"
        if c not in found:
            found.append(c)
    return found


def _web_search(company_name: str, nse_symbol: Optional[str]) -> list[str]:
    q = f'site:valueresearchonline.com/stocks "{short_name(company_name)}"'
    urls: list[str] = []
    for engine in (f"https://html.duckduckgo.com/html/?q={quote_plus(q)}",
                   f"https://lite.duckduckgo.com/lite/?q={quote_plus(q)}",
                   f"https://www.bing.com/search?q={quote_plus(q)}&setlang=en-IN",
                   f"https://search.yahoo.com/search?p={quote_plus(q)}"):
        try:
            urls += [u for u in _search_urls(_get(engine, 12)) if u not in urls]
        except Exception as e:  # noqa: BLE001 - one engine failing is fine
            log.info("Value Research search via %s failed: %s", engine.split('/')[2], e)
        if urls:
            break
    return urls[:5]


def _ai_search(company_name: str, nse_symbol: Optional[str]) -> list[str]:
    from analysis import llm

    if not llm.is_available():
        return []
    try:
        res = llm.generate_grounded(
            f"Find the Value Research Online stock page (valueresearchonline.com/stocks/<number>/<name>/) for the "
            f"Indian listed company {company_name}" + (f" (NSE: {nse_symbol})" if nse_symbol else "") +
            ". Reply with the URL only.")
        text = res.get("text", "")
        return _search_urls(f"{text} " + " ".join(str(x.get("url", "")) for x in res.get("sources", [])))
    except Exception as e:  # noqa: BLE001
        log.info("Value Research AI search failed: %s", e)
        return []


def _matches_company(text: str, nse_symbol: Optional[str], bse_code: Optional[str], company_name: str) -> bool:
    t = text.upper()
    if nse_symbol and re.search(r"NSE\s*:?\s*" + re.escape(nse_symbol.upper()) + r"\b", t):
        return True
    if bse_code and re.search(r"BSE\s*:?\s*" + re.escape(str(bse_code)) + r"\b", t):
        return True
    if not nse_symbol and not bse_code:
        return short_name(company_name).upper() in t
    return False


def find_page(company_name: str, nse_symbol: Optional[str], bse_code: Optional[str],
              company_id: Optional[int] = None) -> tuple[Optional[str], Optional[str], str]:
    """Returns (url, html, how) for the company's Value Research stock page, or (None, None, reason)."""
    saved = None
    if company_id:
        try:
            from core import repository as repo

            saved = repo.get_link(company_id, SITE)
        except Exception:  # noqa: BLE001
            saved = None
    tried = []
    for how, candidates in (("saved link", lambda: [saved] if saved else []),
                            ("web search", lambda: _web_search(company_name, nse_symbol)),
                            ("AI search", lambda: _ai_search(company_name, nse_symbol))):
        for url in candidates():
            if not url or url in tried:
                continue
            tried.append(url)
            try:
                html = _get(url)
            except Exception as e:  # noqa: BLE001
                log.info("Value Research page %s: %s", url, e)
                continue
            if how == "saved link" or _matches_company(_text(html), nse_symbol, bse_code, company_name):
                if company_id and how != "saved link":
                    try:
                        from core import repository as repo

                        repo.save_link(company_id, SITE, url, "ai" if how == "AI search" else "search")
                    except Exception:  # noqa: BLE001
                        pass
                return url, html, how
    if not tried:
        return None, None, "stock page not found by search (paste it on the Key Ratios tab)"
    return None, None, f"{len(tried)} page(s) checked, none showed this company's NSE/BSE code"


# ------------------------------------------------------------------ parsing
def _text(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    return soup.get_text("\n")


def _tokens(html: str) -> list[str]:
    return [t for t in (clean_text(x) for x in _text(html).split("\n")) if t]


def _value_after(tokens: list[str], label: str, kind: str, look: int = 6) -> Optional[str]:
    low = label.lower()
    for i, tok in enumerate(tokens):
        if tok.lower().rstrip(":") != low:
            continue
        window = tokens[i + 1:i + 1 + look]
        joined = " ".join(window)
        if kind == "score":
            m = re.search(r"\b(\d{1,2})\s*/\s*10\b", joined)
            if m and 0 <= int(m.group(1)) <= 10:
                return f"{int(m.group(1))}/10"
        elif kind == "word":
            # the page draws the whole Low / Moderate / High scale; use it only when one level is shown
            words = {w.lower() for w in window if w.lower() in ("low", "moderate", "high", "very high", "very low")}
            if len(words) == 1:
                return words.pop().title()
        else:
            for w in window:
                if w in ("--", "-", "NA", "N/A"):
                    return None
                m = re.fullmatch(r"(?:₹\s*)?(" + _NUM + r")\s*(?:x|times|%)?", w.replace(" ", ""))
                if m:
                    return m.group(1)
    return None


def _returns_table(html: str, company_name: str) -> list[dict]:
    """Rows of the performance table (company vs Sensex vs sector index): [{'name', '1 Year', '3 Years', ...}]."""
    import pandas as pd

    try:
        tables = pd.read_html(io.StringIO(html))
    except Exception:  # noqa: BLE001
        return []
    for df in tables:
        cols = [str(c).strip() for c in df.columns]
        if "1 Year" in cols and "3 Years" in cols:
            df.columns = cols
            rows = []
            for _, r in df.iterrows():
                rows.append({k: (None if pd.isna(v) else v) for k, v in r.items()})
            return rows
    return []


def _pe_pb_history(html: str) -> list[dict]:
    import pandas as pd

    try:
        tables = pd.read_html(io.StringIO(html))
    except Exception:  # noqa: BLE001
        return []
    for df in tables:
        cols = [str(c).strip() for c in df.columns]
        if cols and cols[0].lower() == "year" and any("p/e" in c.lower() for c in cols):
            out = []
            for _, r in df.iterrows():
                vals = list(r.values)
                try:
                    out.append({"year": str(int(float(vals[0]))), "pe": float(vals[1]),
                                "pb": float(vals[2]) if len(vals) > 2 else None})
                except (TypeError, ValueError):
                    continue
            return out
    return []


def parse_page(html: str, url: str, company_name: str) -> dict:
    tokens = _tokens(html)
    full = " ".join(tokens)
    items: list[dict] = []

    def add(metric: str, value: str, why: str, period: str = "latest") -> None:
        items.append({"metric": metric, "value": value, "period": period, "source": SITE, "url": url,
                      "via": "Value Research page", "why": why})

    for label, metric, why, kind in LABELS:
        v = _value_after(tokens, label, kind)
        if v is None:
            continue
        add(metric, v + ("x" if kind == "x" else ""), why)

    m = re.search(r"P/E ratio(?:(?!P/B).){0,140}?peer median of\s*(" + _NUM + r")", full, re.I)
    if m:
        add("Peer median P/E", f"{m.group(1)}x", "the company's P/E compared with its peers")
    m = re.search(r"P/B ratio(?:(?!P/E).){0,140}?peer median of\s*(" + _NUM + r")", full, re.I)
    if m:
        add("Peer median P/B", f"{m.group(1)}x", "the company's P/B compared with its peers")
    m = re.search(r"classified as (?:a )?(Large|Mid|Small|Micro)[ -]?Cap", full, re.I)
    if m:
        add("Market-cap category", f"{m.group(1).title()} cap", "size category used by fund managers")

    rows = _returns_table(html, company_name)
    if rows:
        first = rows[0]
        name_key = next(iter(first))
        others = [r for r in rows[1:3]]
        for col in ("1 Year", "3 Years", "5 Years", "10 Years"):
            if first.get(col) is None:
                continue
            try:
                own = float(str(first[col]).replace(",", ""))
            except ValueError:
                continue
            cmp_txt = "; ".join(f"{r[name_key]} {float(str(r[col]).replace(',', '')):+.1f}%"
                                for r in others if r.get(col) is not None and _isnum(r[col]))
            add(f"Share price return, {col.lower()}" + (" (annualised)" if col != "1 Year" else ""),
                f"{own:+.1f}%" + (f" (vs {cmp_txt})" if cmp_txt else ""),
                "price performance against the market and the sector index")

    hist = _pe_pb_history(html)
    if hist:
        add("Year-end P/E history", ", ".join(f"{h['year']}: {h['pe']:.1f}x" for h in hist[:5]),
            "how the market valued the company in past years")
        if any(h.get("pb") is not None for h in hist):
            add("Year-end P/B history", ", ".join(f"{h['year']}: {h['pb']:.2f}x" for h in hist[:5]
                                                  if h.get("pb") is not None),
                "price-to-book in past years")
    return {"items": items, "url": url}


def _isnum(v: Any) -> bool:
    try:
        float(str(v).replace(",", ""))
        return True
    except ValueError:
        return False


def fetch_valueresearch(company_name: str, nse_symbol: Optional[str], bse_code: Optional[str],
                        company_id: Optional[int] = None) -> dict:
    """{'items': [...], 'url': page, 'how': 'web search' ...} or {'error': reason}. Never raises."""
    try:
        url, html, how = find_page(company_name, nse_symbol, bse_code, company_id)
        if not url:
            return {"error": how}
        res = parse_page(html, url, company_name)
        res["how"] = how
        if not res["items"]:
            res["error"] = "page opened but no values could be read (layout may have changed)"
        return res
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
