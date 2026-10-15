"""Company and market news from the stock exchange and six Indian business news websites.

Sources (fixed order, also the order used in reports):
    NSE (the company's own exchange filings) · Economic Times · Moneycontrol · Business Standard · Mint ·
    CNBC-TV18 · The Hindu BusinessLine

Company news is strictly about the company: a headline is kept only if its TITLE names the company
(short name, e.g. "ICICI Bank", or its NSE symbol). General market, economy or unrelated stories are
dropped - they belong on the Market News page, not in a company report.

How headlines are collected:
  * market news  - the websites' own RSS feeds (markets / stocks sections);
  * company news - the same RSS feeds filtered by company name or NSE symbol, plus a Google News
                   search restricted to each website ("<company>" site:<domain>), because RSS feeds
                   only keep the latest few dozen stories.
Only the headline, link, website name and date are kept - never the article text.
"""
from __future__ import annotations

import re
from collections import Counter, OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from time import mktime
from typing import Optional
from urllib.parse import quote_plus, urlparse

import feedparser
import requests

from core.utils import clean_text

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/126.0 Safari/537.36"}

# name, domain, RSS feeds (markets/companies). A dead feed is skipped; Google News site search still covers the site.
# "api": company announcements read from the exchange's own API (NSE by symbol, BSE by scrip code).
NEWS_SOURCES: list[dict] = [
    {"name": "NSE", "domain": "nseindia.com", "google": False, "api": "nse", "feeds": [
        "https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml",
        "https://nsearchives.nseindia.com/content/RSS/Financial_Results.xml",
        "https://nsearchives.nseindia.com/content/RSS/Board_Meetings.xml",
    ]},
    {"name": "BSE", "domain": "bseindia.com", "google": False, "api": "bse", "feeds": []},
    {"name": "Economic Times", "domain": "economictimes.indiatimes.com", "feeds": [
        "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
        "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    ]},
    {"name": "Moneycontrol", "domain": "moneycontrol.com", "feeds": [
        "https://www.moneycontrol.com/rss/marketreports.xml",
        "https://www.moneycontrol.com/rss/business.xml",
        "https://www.moneycontrol.com/rss/latestnews.xml",
    ]},
    {"name": "Business Standard", "domain": "business-standard.com", "feeds": [
        "https://www.business-standard.com/rss/markets-106.rss",
        "https://www.business-standard.com/rss/companies-101.rss",
    ]},
    {"name": "Mint", "domain": "livemint.com", "feeds": [
        "https://www.livemint.com/rss/markets",
        "https://www.livemint.com/rss/companies",
    ]},
    {"name": "CNBC-TV18", "domain": "cnbctv18.com", "feeds": [
        "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/market.xml",
        "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/business.xml",
    ]},
    {"name": "The Hindu BusinessLine", "domain": "thehindubusinessline.com", "feeds": [
        "https://www.thehindubusinessline.com/markets/stock-markets/feeder/default.rss",
        "https://www.thehindubusinessline.com/companies/feeder/default.rss",
    ]},
    {"name": "Financial Express", "domain": "financialexpress.com", "feeds": [
        "https://www.financialexpress.com/market/feed/",
        "https://www.financialexpress.com/business/feed/",
    ]},
    {"name": "Business Today", "domain": "businesstoday.in", "feeds": []},
    {"name": "NDTV Profit", "domain": "ndtvprofit.com", "feeds": []},
    {"name": "Zee Business", "domain": "zeebiz.com", "feeds": []},
    {"name": "Reuters", "domain": "reuters.com", "feeds": []},
]
from core.config import get_settings  # noqa: E402

PER_SOURCE = get_settings().news_per_source or 15   # headlines fetched and kept per website (.env NEWS_PER_SOURCE)
COMPANY_DAYS = 90      # how far back company news is searched
SOURCE_NAMES = [s["name"] for s in NEWS_SOURCES]
MEDIA_SOURCES = [s for s in NEWS_SOURCES if not s.get("api")]   # news websites (not the exchanges)

_SUFFIX = re.compile(r"\b(ltd|limited|pvt|private|inc|corp(oration)?|co)\.?$", re.I)

# keyword themes used for grouping and for rule-based insights; "x*" = word starting with x, else whole word
THEMES: list[tuple[str, tuple[str, ...]]] = [
    ("Results and earnings", ("result*", "profit*", "revenue*", "earnings", "q1", "q2", "q3", "q4", "quarter*",
                              "net income", "margin*", "ebitda", "guidance", "nii", "npa*", "loan growth")),
    ("Dividends and buybacks", ("dividend*", "buyback*", "bonus", "split", "record date")),
    ("Deals, orders and expansion", ("acqui*", "merger*", "stake*", "order*", "contract*", "deal*", "launch*",
                                     "expansion", "expand*", "capex", "plant*", "partnership*", "joint venture",
                                     "ipo", "fundrais*", "qip", "raises")),
    ("Management and governance", ("ceo", "md", "chairman", "director*", "resign*", "appoint*", "board",
                                   "promoter*", "pledge*", "esop*")),
    ("Regulation, legal and tax", ("rbi", "sebi", "penalt*", "court", "tax", "gst", "probe", "regulator*",
                                   "fine*", "ban", "banned", "show cause", "scn", "licence", "license")),
    ("Brokerage views and ratings", ("target price", "price target", "rating", "ratings", "upgrade*",
                                     "downgrade*", "brokerage*", "buy call", "sell call", "outperform",
                                     "underperform", "overweight", "underweight")),
    ("Share price moves", ("shares", "stock", "surge*", "jump*", "rally", "rallies", "fall*", "slump*", "52-week",
                           "record high", "top gainer*", "top loser*", "plunge*", "m-cap", "market cap*")),
]
_THEME_RX = [(name, re.compile("|".join(
    r"(?<![a-z0-9])" + re.escape(w[:-1]) if w.endswith("*") else r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])"
    for w in words))) for name, words in THEMES]

# headlines that are web pages about many companies, not news about this company
_GENERIC = re.compile(r"(share market live|market live updates|stock market today|stocks to watch|stocks to buy|"
                      r"ipo date:|ipo gmp|who am i\?|quiz|bank holidays|top gainers and losers|sensex today|"
                      r"nifty today|closing bell|opening bell)", re.I)
_TRAILING_GENERIC = re.compile(r"\s+(industries|enterprises|services|corporation|company|india)$", re.I)


def short_name(name: str) -> str:
    n = clean_text(name)
    for _ in range(2):
        n = _SUFFIX.sub("", n).strip(" .,&")
    return n


def source_for_url(url: str) -> Optional[str]:
    host = urlparse(url or "").netloc.lower()
    for s in NEWS_SOURCES:
        if host == s["domain"] or host.endswith("." + s["domain"]):
            return s["name"]
    return None


# ------------------------------------------------------------------ low-level feed reading
def _parse_feed(url: str, timeout: int = 15) -> list:
    r = requests.get(url, timeout=timeout, headers=HEADERS)
    r.raise_for_status()
    return feedparser.parse(r.content).entries


def _when(entry) -> Optional[datetime]:
    for key in ("published_parsed", "updated_parsed"):
        if entry.get(key):
            try:
                return datetime.fromtimestamp(mktime(entry[key]), tz=timezone.utc)
            except (OverflowError, ValueError, TypeError):
                return None
    return None


def _item(entry, source: str, via: str) -> Optional[dict]:
    title = clean_text(entry.get("title", ""))
    link = entry.get("link")
    if not title or not link:
        return None
    gsrc = entry.get("source")
    if isinstance(gsrc, dict) and gsrc.get("title") and title.endswith(f" - {gsrc['title']}"):
        title = title[: -len(gsrc["title"]) - 3]
    summary = clean_text(re.sub(r"<[^>]+>", " ", entry.get("summary", "") or ""))[:300]
    return {"title": title, "url": link, "source": source, "published_at": _when(entry), "summary": summary,
            "via": via}


def _dedupe_sort(items: list[dict], limit: Optional[int] = None) -> list[dict]:
    seen, out = set(), []
    for it in items:
        key = re.sub(r"[^a-z0-9 ]", "", it["title"].lower())[:80]
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    out.sort(key=lambda x: x["published_at"] or datetime(1970, 1, 1, tzinfo=timezone.utc), reverse=True)
    return out[:limit] if limit else out


def _source_feed_items(src: dict) -> tuple[list[dict], list[str]]:
    items, errors = [], []
    for url in src["feeds"]:
        try:
            for e in _parse_feed(url):
                it = _item(e, src["name"], "rss")
                if it and src["name"] == "NSE" and it.get("summary"):
                    # NSE filing feeds put the company in the title and the subject in the description
                    it["title"] = f"{it['title']}: {it['summary']}"[:300]
                if it:
                    items.append(it)
        except Exception as e:  # noqa: BLE001 - one dead feed must not stop the others
            errors.append(f"{src['name']}: {type(e).__name__}")
    return items, errors


# ------------------------------------------------------------------ market news (home page)
def fetch_market_news(days: int = 3, per_source: int = 25) -> dict:
    """Latest general stock-market headlines from the news websites (exchanges excluded).

    Returns {"items": [...], "errors": [...], "fetched_at": iso}.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    items, errors = [], []

    def one(src: dict) -> tuple[list[dict], list[str]]:
        got, errs = _source_feed_items(src)
        if not got:   # no RSS feed (or it failed): Google News search limited to that website
            try:
                got = _google_site_search('"stock market" OR Sensex OR Nifty OR shares', src, max(days, 1))
            except Exception as e:  # noqa: BLE001
                errs.append(f"{src['name']}: Google News {type(e).__name__}")
        return got, errs

    with ThreadPoolExecutor(max_workers=8) as ex:
        for src_items, errs in ex.map(one, MEDIA_SOURCES):
            fresh = [i for i in src_items if not i["published_at"] or i["published_at"] >= cutoff]
            items += _dedupe_sort(fresh, per_source)
            errors += errs
    return {"items": _dedupe_sort(items), "errors": errors,
            "fetched_at": datetime.now(timezone.utc).isoformat()}


# ------------------------------------------------------------------ company news (company page + report)
def _matches(title: str, needles: list[str]) -> bool:
    t = f" {title.lower()} "
    return any(n and re.search(r"(?<![a-z0-9])" + re.escape(n.lower()) + r"(?![a-z0-9])", t) for n in needles)


def company_needles(company_name: str, nse_symbol: Optional[str] = None) -> list[str]:
    """Names a headline must contain to count as news about this company."""
    base = short_name(company_name)
    needles = [base]
    alt = _TRAILING_GENERIC.sub("", base).strip()
    if alt != base and len(alt.split()) >= 2:   # "Tata Consultancy Services" -> "Tata Consultancy"
        needles.append(alt)
    if nse_symbol and len(nse_symbol) >= 3 and nse_symbol.upper() != base.upper():
        needles.append(nse_symbol)
    return needles


def is_company_news(title: str, needles: list[str]) -> bool:
    """True only when the headline itself names the company and is not a generic multi-company page."""
    if not title or _GENERIC.search(title):
        return False
    if not _matches(title, needles):
        return False
    stripped = re.sub(r"[\s.]+$", "", title.strip()).lower()
    if any(stripped in (n.lower(), n.lower() + " ltd", n.lower() + " limited") for n in needles):
        return False      # a bare stock-quote page title such as "ICICI Bank Ltd."
    return True


def filter_company_news(items: list[dict], company_name: str, nse_symbol: Optional[str] = None) -> list[dict]:
    needles = company_needles(company_name, nse_symbol)
    return [i for i in items if is_company_news(i.get("title", ""), needles)]


def _google_site_search(query: str, src: dict, days: int) -> list[dict]:
    q = f'{query} site:{src["domain"]} when:{days}d'
    url = f"https://news.google.com/rss/search?q={quote_plus(q)}&hl=en-IN&gl=IN&ceid=IN:en"
    out = []
    for e in _parse_feed(url):
        it = _item(e, src["name"], "google_news")
        if it:
            out.append(it)
    return out


# ------------------------------------------------------------------ exchange announcements (official APIs)
NSE_HOME = "https://www.nseindia.com"
NSE_ANN_API = "https://www.nseindia.com/api/corporate-announcements?index=equities&symbol={sym}"
BSE_ANN_API = ("https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=1&strCat=-1"
               "&strPrevDate={frm}&strScrip={code}&strSearch=P&strToDate={to}&strType=C&subcategory=-1")
BSE_PDF = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/{name}"


def _parse_dt(text: str) -> Optional[datetime]:
    text = (text or "").strip()
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%b-%Y", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M:%S"):
        try:
            return datetime.strptime(text[:26], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def fetch_nse_announcements(nse_symbol: str, company_name: str, limit: int = PER_SOURCE) -> list[dict]:
    """Corporate announcements filed on NSE by this company (results, board meetings, orders, etc.)."""
    sess = requests.Session()
    sess.headers.update({**HEADERS, "Accept": "application/json", "Referer": NSE_HOME + "/"})
    sess.get(NSE_HOME, timeout=12)                       # NSE needs its cookies first
    r = sess.get(NSE_ANN_API.format(sym=quote_plus(nse_symbol.upper())), timeout=15)
    r.raise_for_status()
    data = r.json()
    rows = data if isinstance(data, list) else (data.get("data") or [])
    out = []
    for row in rows[: limit * 2]:
        subject = clean_text(row.get("desc") or "")
        detail = clean_text(row.get("attchmntText") or "")
        name = clean_text(row.get("sm_name") or company_name)
        if not (subject or detail):
            continue
        title = f"{name}: {subject}" + (f" – {detail}" if detail and detail.lower() != subject.lower() else "")
        url = row.get("attchmntFile") or f"{NSE_HOME}/get-quotes/equity?symbol={quote_plus(nse_symbol)}"
        out.append({"title": title[:300], "url": url, "source": "NSE",
                    "published_at": _parse_dt(row.get("sort_date") or row.get("an_dt") or ""),
                    "summary": detail[:300], "via": "nse_api"})
    return _dedupe_sort(out, limit)


def fetch_bse_announcements(bse_code: str, company_name: str, days: int = COMPANY_DAYS,
                            limit: int = PER_SOURCE) -> list[dict]:
    """Corporate announcements filed on BSE (by BSE scrip code)."""
    to = datetime.now()
    frm = to - timedelta(days=days)
    r = requests.get(BSE_ANN_API.format(code=quote_plus(str(bse_code)), frm=frm.strftime("%Y%m%d"),
                                        to=to.strftime("%Y%m%d")),
                     headers={**HEADERS, "Accept": "application/json", "Referer": "https://www.bseindia.com/",
                              "Origin": "https://www.bseindia.com"}, timeout=15)
    r.raise_for_status()
    rows = (r.json() or {}).get("Table") or []
    out = []
    for row in rows[: limit * 2]:
        subject = clean_text(row.get("NEWSSUB") or row.get("HEADLINE") or "")
        if not subject:
            continue
        if not subject.lower().startswith(short_name(company_name).lower()[:10]):
            subject = f"{short_name(company_name)}: {subject}"
        att = row.get("ATTACHMENTNAME")
        url = BSE_PDF.format(name=att) if att else row.get("NSURL") or \
            f"https://www.bseindia.com/stock-share-price/x/x/{bse_code}/corp-announcements/"
        out.append({"title": subject[:300], "url": url, "source": "BSE",
                    "published_at": _parse_dt(row.get("NEWS_DT") or row.get("DissemDT") or ""),
                    "summary": clean_text(row.get("CATEGORYNAME") or "")[:300], "via": "bse_api"})
    return _dedupe_sort(out, limit)


def fetch_company_news(company_name: str, nse_symbol: Optional[str] = None, days: int = COMPANY_DAYS,
                       per_source: int = PER_SOURCE, bse_code: Optional[str] = None) -> list[dict]:
    """Up to `per_source` recent headlines naming the company from every source.

    NSE / BSE: the company's own filings from the exchange APIs (NSE RSS filtered by name as a fallback).
    News websites: their RSS feeds + Google News searches limited to that website (by name and by NSE symbol).
    Every headline must name the company in its title (general market news is dropped).
    """
    base = short_name(company_name)
    needles = company_needles(company_name, nse_symbol)
    queries = [f'"{base}"']
    if nse_symbol and nse_symbol.upper() != base.upper() and len(nse_symbol) >= 3:
        queries.append(f'"{nse_symbol.upper()}" share')
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    def per_site(src: dict) -> list[dict]:
        found: list[dict] = []
        try:
            if src.get("api") == "nse" and nse_symbol:
                found += fetch_nse_announcements(nse_symbol, company_name, per_source)
            elif src.get("api") == "bse" and bse_code:
                found += fetch_bse_announcements(bse_code, company_name, days, per_source)
        except Exception:  # noqa: BLE001 - the exchanges sometimes refuse scripts; RSS below still runs
            pass
        if len(found) < per_source:
            feed_items, _ = _source_feed_items(src)
            found += feed_items
        if src.get("google", True):
            for q in queries:
                try:
                    found += _google_site_search(q, src, days)
                except Exception:  # noqa: BLE001 - news is best-effort
                    pass
        # Google matches words anywhere on a page (menus, tickers), so the TITLE must name the company
        found = [i for i in found if is_company_news(i["title"], needles)
                 and (not i["published_at"] or i["published_at"] >= cutoff)]
        return _dedupe_sort(found, per_source)

    items: list[dict] = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for res in ex.map(per_site, NEWS_SOURCES):
            items += res
    return _dedupe_sort(items)


def news_counts(items: list[dict]) -> "OrderedDict[str, int]":
    """Headlines per source in the fixed source order (0 when a source had none)."""
    c = Counter(canonical_source(i.get("source"), i.get("url", "")) for i in items)
    return OrderedDict((n, c.get(n, 0)) for n in SOURCE_NAMES)


def fetch_news(company_name: str, nse_symbol: str | None = None, days: int = COMPANY_DAYS,
               bse_code: Optional[str] = None) -> list[dict]:
    """Entry point used by core.services.refresh_news(): up to PER_SOURCE headlines from every source."""
    return fetch_company_news(company_name, nse_symbol, days=days, bse_code=bse_code)


# ------------------------------------------------------------------ grouping and insights
_ALIASES = {"the economic times": "Economic Times", "economic times": "Economic Times", "et": "Economic Times",
            "et markets": "Economic Times", "moneycontrol.com": "Moneycontrol", "moneycontrol": "Moneycontrol",
            "business standard": "Business Standard", "mint": "Mint", "livemint": "Mint", "mint (livemint)": "Mint",
            "the hindu businessline": "The Hindu BusinessLine", "businessline": "The Hindu BusinessLine",
            "the hindu business line": "The Hindu BusinessLine", "cnbc tv18": "CNBC-TV18", "cnbctv18": "CNBC-TV18",
            "cnbc-tv18": "CNBC-TV18", "cnbctv18.com": "CNBC-TV18", "nse": "NSE", "nse india": "NSE",
            "bse": "BSE", "bse india": "BSE", "financial express": "Financial Express",
            "the financial express": "Financial Express", "business today": "Business Today",
            "businesstoday": "Business Today", "ndtv profit": "NDTV Profit", "ndtvprofit": "NDTV Profit",
            "bq prime": "NDTV Profit", "zee business": "Zee Business", "zeebiz": "Zee Business",
            "reuters": "Reuters", "reuters india": "Reuters"}


def canonical_source(name: Optional[str], url: str = "") -> Optional[str]:
    """Map a stored source label or URL to one of the known source names (None if it is another site)."""
    if name in SOURCE_NAMES:
        return name
    alias = _ALIASES.get((name or "").strip().lower())
    return alias or source_for_url(url)


def only_five_sources(items: list[dict]) -> list[dict]:
    out = []
    for it in items:
        src = canonical_source(it.get("source"), it.get("url", ""))
        if src:
            out.append({**it, "source": src})
    return out


# How important a headline is for an investor (used to pick the "main" headlines per website).
_IMPORTANT = re.compile(r"\b(result|results|q[1-4]|quarter|profit|revenue|earnings|guidance|outlook|order|orders|"
                        r"contract|deal|acqui|merger|demerger|stake|dividend|buyback|bonus|split|rating|downgrade|"
                        r"upgrade|target|ceo|cfo|md\b|resign|appoint|layoff|fund ?rais|qip|ipo|penalty|probe|"
                        r"lawsuit|tax demand|expansion|capex|launch|partnership|board meeting)", re.I)
_ROUTINE = re.compile(r"(trading window|loss of share certificate|duplicate share|compliance certificate|"
                      r"certificate under regulation|regulation 74|esop|esos|rsu|allotment of|newspaper (publication|"
                      r"advertisement)|investor presentation intimation|closure of trading|xbrl|copy of newspaper|"
                      r"reg\.? ?39|change in (registrar|rta)|analysts?/institutional investor meet)", re.I)


def importance(title: str) -> int:
    t = title or ""
    return (2 if _IMPORTANT.search(t) else 0) - (3 if _ROUTINE.search(t) else 0)


def group_by_source(items: list[dict], per_source: int = PER_SOURCE,
                    main_first: bool = False) -> "OrderedDict[str, list[dict]]":
    """Source name -> its headlines, in the fixed source order. Other websites are left out.

    main_first=True picks the most important headlines first (results, orders, deals, dividends, management
    changes ...), routine filings last, then shows the chosen ones newest first."""
    groups: "OrderedDict[str, list[dict]]" = OrderedDict((n, []) for n in SOURCE_NAMES)

    def _date(it: dict) -> str:
        return str(it.get("published_at") or "")

    pool = sorted(only_five_sources(items), key=_date, reverse=True)
    if main_first:
        pool = sorted(pool, key=lambda it: importance(it.get("title", "")), reverse=True)   # stable: keeps date order
    for it in pool:
        if len(groups[it["source"]]) < per_source:
            groups[it["source"]].append(it)
    return OrderedDict((k, sorted(v, key=_date, reverse=True)) for k, v in groups.items() if v)


def theme_of(title: str) -> Optional[str]:
    low = title.lower()
    for name, rx in _THEME_RX:
        if rx.search(low):
            return name
    return None


def rule_based_insights(items: list[dict], subject: str = "") -> list[str]:
    """Data-driven points from the headlines when the AI is not available (no guessing)."""
    if not items:
        return []
    by_theme: dict[str, list[dict]] = {}
    for it in items:
        th = theme_of(it["title"])
        if th:
            by_theme.setdefault(th, []).append(it)
    out = []
    srcs = Counter(it.get("source") or "Other" for it in items)
    out.append(f"{len(items)} recent headline(s){(' about ' + subject) if subject else ''} from "
               f"{len(srcs)} website(s); most coverage from {srcs.most_common(1)[0][0]}.")
    for th, lst in sorted(by_theme.items(), key=lambda kv: -len(kv[1]))[:5]:
        sites = sorted({i.get('source') or 'Other' for i in lst})
        out.append(f"{th}: {len(lst)} headline(s) ({', '.join(sites)}). Latest: “{lst[0]['title']}”.")
    return out


def ai_insights(items: list[dict], subject: str = "") -> tuple[list[str], str]:
    """Key points from the headlines, written by Gemini; falls back to rule_based_insights.

    Returns (points, method) where method is the model name or 'rule-based'.
    """
    from pydantic import BaseModel, Field

    from analysis import llm

    if not items:
        return [], "none"
    if not llm.is_available():
        return rule_based_insights(items, subject), "rule-based"

    class Insights(BaseModel):
        points: list[str] = Field(description="4 to 6 key points")

    heads = [{"source": i.get("source"), "date": str(i.get("published_at") or "")[:10], "title": i["title"]}
             for i in items[:40]]
    prompt = (f"Below are recent news headlines{(' about ' + subject) if subject else ' from Indian stock markets'}. "
              "Write 4 to 6 key points an investor should know. Use ONLY what the headlines say; do not add facts, "
              "numbers or predictions that are not in them. Name the website in brackets after each point, e.g. "
              "(Mint). No buy/sell advice.\n\nHEADLINES:\n" + "\n".join(
                  f"- [{h['source']}] {h['date']} {h['title']}" for h in heads))
    try:
        res = llm.generate_json(prompt, Insights, system="You are a careful financial news editor.")
        pts = [p.strip() for p in res.get("points", []) if p and p.strip()]
        if pts:
            return pts[:6], llm.model_name()
    except Exception:  # noqa: BLE001
        pass
    return rule_based_insights(items, subject), "rule-based"
